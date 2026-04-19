"""
Cortex LangGraph Supervisor
Orchestrates multi-step code intelligence using Groq (primary) and Gemini (fallback),
along with a Critic node for self-healing hallucination checks.
"""

from typing import Annotated, Any, Literal, TypedDict
import json
import operator

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from core.config import settings
from core.logger import get_logger
from agents.tools import ALL_TOOLS
from models.schemas import HistoryMessage

# For fallback model
from google import genai
from langchain_core.language_models.chat_models import BaseChatModel

logger = get_logger(__name__)


class AgentState(TypedDict):
    """LangGraph State."""
    messages: Annotated[list[BaseMessage], add_messages]
    context: Annotated[list[str], operator.add]
    loop_count: int


# Optional simple wrapper for Gemini 2.5 Flash in Langchain if full support is missing, 
# but Langchain has `ChatGoogleGenerativeAI`. We'll just define the initialization safely.
def _get_llms() -> tuple[BaseChatModel | None, BaseChatModel | None]:
    try:
        groq_llm = ChatGroq(
            api_key=settings.groq_api_key,
            model_name="llama-3.3-70b-versatile",
            temperature=0.1,
            max_tokens=2048,
        ).bind_tools(ALL_TOOLS)
    except Exception as e:
        logger.warning(f"Failed to initialize Groq LLM: {e}")
        groq_llm = None

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        gemini_llm = ChatGoogleGenerativeAI(
            google_api_key=settings.gemini_api_key,
            model="gemini-2.5-flash",
            temperature=0.1,
        ).bind_tools(ALL_TOOLS)
    except Exception as e:
        logger.warning(f"Failed to initialize Gemini fallback LLM: {e}")
        gemini_llm = None

    return groq_llm, gemini_llm


GROQ_LLM, GEMINI_LLM = _get_llms()

if not GROQ_LLM and not GEMINI_LLM:
    logger.error("NO LLMS CONFIGURED. Agent will fail.")

SYSTEM_PROMPT = """
You are Cortex, an elite Code Intelligence Agent.
You have access to 7 tools for exploring indexed codebases.

RULES:
- NEVER guess. Always use tools to find actual source code.
- Maximum 3 tool calls before synthesizing your final answer.
- Always cite: file path, function name, line numbers.
- If the query is ambiguous, call ask_human_for_clarification.
- Format code in markdown with correct language tags.
"""

CRITIC_PROMPT = """
You are the Cortex Critic Node.
Your job is to review the drafted answer from the Cortex Agent against the retrieved tool context.
Determine if the Agent's answer is grounded in the retrieved context, or if it contains hallucinations/guesses.
If you find hallucinations, explain why and flag 'hallucinated'.
If it is completely grounded or correctly states that it cannot find the information, flag 'grounded'.
Respond with a JSON object: {"status": "hallucinated" | "grounded", "reason": "..."}
"""

tool_node = ToolNode(ALL_TOOLS)

def agent_node(state: AgentState) -> dict:
    """The main reasoning agent."""
    messages = state["messages"]
    new_loop_count = state.get("loop_count", 0) + 1
    
    # Ensure system prompt is first
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        
    try:
        if GROQ_LLM:
            response = GROQ_LLM.invoke(messages)
        else:
            response = GEMINI_LLM.invoke(messages)
    except Exception as e:
        logger.warning(f"Primary LLM failed: {e}. Attempting fallback.")
        if GEMINI_LLM:
            response = GEMINI_LLM.invoke(messages)
        else:
             response = AIMessage(content="Error: All LLMs failed.")
             
    return {"messages": [response], "loop_count": new_loop_count}


def critic_node(state: AgentState) -> dict:
    """Self-healing node to check for hallucinations."""
    messages = state["messages"]
    
    # Get the last AI message
    last_message = messages[-1]
    if not isinstance(last_message, AIMessage) or last_message.tool_calls:
         # Should not happen based on routing, but safety check
         return {"messages": []}
         
    draft_answer = last_message.content
    
    # Extract all tool responses to form the context
    tool_contexts = [
        msg.content for msg in messages 
        if isinstance(msg, ToolMessage)
    ]
    context_str = "\n".join(tool_contexts)
    
    critic_prompt = (
        f"{CRITIC_PROMPT}\n\n"
        f"TOOL CONTEXT:\n{context_str}\n\n"
        f"DRAFT ANSWER:\n{draft_answer}\n\n"
        f"Provide your JSON evaluation:"
    )
    
    try:
        # Critic can safely run on fast fallback LLM
        llm = GEMINI_LLM if GEMINI_LLM else GROQ_LLM
        # temporarily unbind tools for JSON response
        strict_llm = llm.with_config({"tags": ["critic"]}) if not hasattr(llm, "bind") else llm.kwargs.get("llm", llm)
        if callable(getattr(strict_llm, "with_structured_output", None)):
             # We just do a simple invoke and parse
             pass

        raw_response = llm.invoke([HumanMessage(content=critic_prompt)])
        content = raw_response.content
        
        # very simple json extraction
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
             eval_data = json.loads(content[start:end])
        else:
             # Assume grounded if parsing fails
             eval_data = {"status": "grounded", "reason": "Parse failure"}
             
    except Exception as e:
        logger.warning(f"Critic node failed: {e}. Assuming grounded.")
        eval_data = {"status": "grounded", "reason": str(e)}

    if eval_data.get("status") == "hallucinated":
        logger.info(f"Critic flagged hallucination: {eval_data.get('reason')}")
        correction_msg = SystemMessage(
            content=f"CRITIC WARNING: Your previous answer contained hallucinations. "
                    f"Reason: {eval_data.get('reason')}. "
                    f"Please try again using ONLY the retrieved context, or admit you don't know."
        )
        return {"messages": [correction_msg]}
    
    return {"messages": []} # No change needed


def route_from_agent(state: AgentState) -> Literal["tools", "critic", END]: # type: ignore
    """Decide where to go after the agent generates a response."""
    messages = state["messages"]
    last_message = messages[-1]
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
        
    return "critic"


def route_from_critic(state: AgentState) -> Literal["agent", END]: # type: ignore
    """Decide where to go after the critic provides feedback."""
    messages = state["messages"]
    last_message = messages[-1]
    
    # If the critic appended a SystemMessage warning, go back to agent
    if isinstance(last_message, SystemMessage) and "CRITIC WARNING" in last_message.content:
        # Prevent infinite loops in self-correction
        if state.get("loop_count", 0) > 6: 
             return END
        return "agent"
        
    return END

# Build Graph
builder = StateGraph(AgentState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_node("critic", critic_node)

builder.set_entry_point("agent")
builder.add_conditional_edges(
    "agent",
    route_from_agent,
    {
        "tools": "tools",
        "critic": "critic",
        END: END
    }
)
builder.add_edge("tools", "agent")
builder.add_conditional_edges(
    "critic",
    route_from_critic,
    {
        "agent": "agent",
        END: END
    }
)

# Compile with a recursion limit explicitly managed
cortex_supervisor = builder.compile()

async def run_agent(query: str, repo: str | None = None, history: list[HistoryMessage] | None = None, user_id: str | None = None) -> list[BaseMessage]:
    """Execute the compiled LangGraph supervisor with tenant isolation."""
    from agents.tools import set_agent_user_context
    
    # Set user context so all tool calls are scoped to this user's data
    set_agent_user_context(user_id)
    
    messages = []
    if history:
         for msg in history[-5:]: # Keep last 5 for context
              if msg.role == "user":
                   messages.append(HumanMessage(content=msg.content))
              elif msg.role == "assistant":
                   messages.append(AIMessage(content=msg.content))
                   
    # Context injection for the query
    q_str = f"User Request: {query}\n"
    if repo:
        q_str += f"Target Repository: {repo}\n"
    else:
        q_str += "Note: No specific repository selected. Search across ALL repositories you have access to.\n"
        
    messages.append(HumanMessage(content=q_str))
    
    config = {"recursion_limit": 10} # includes tool bounces
    final_state = await cortex_supervisor.ainvoke(
        {"messages": messages, "loop_count": 0, "context": []},
        config=config
    )
    
    return final_state["messages"]
