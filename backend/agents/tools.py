"""
Cortex Agent Tools.
Provides LangGraph tools for vector search, graph search, and utility capabilities.
"""

import ast
import operator
from typing import Literal

from langchain_core.tools import tool
from pydantic import Field

from core.logger import get_logger

logger = get_logger(__name__)

# Thread-local context for the current user (set before agent invocation)
_current_user_id: str | None = None
_current_branch: str | None = None

def set_agent_user_context(user_id: str | None, branch: str | None = None):
    """Set the user_id context for agent tool calls. Called before each agent run."""
    global _current_user_id, _current_branch
    _current_user_id = user_id
    _current_branch = branch

def get_agent_user_context() -> str | None:
    """Get the current user_id context."""
    return _current_user_id

def get_agent_branch_context() -> str | None:
    """Get the current branch context for branch-scoped tool calls."""
    return _current_branch

# Lazy loaded singletons
_embedder = None
_vector_store = None
_neo4j = None

def get_embedder():
    global _embedder
    if _embedder is None:
        from indexing.embedder import CortexEmbedder
        _embedder = CortexEmbedder()
    return _embedder

def get_vector_store():
    global _vector_store
    if _vector_store is None:
        from indexing.qdrant_store import VectorStore
        _vector_store = VectorStore()
    return _vector_store

def get_neo4j():
    global _neo4j
    if _neo4j is None:
        from indexing.graph_builder.neo4j_manager import Neo4jManager
        _neo4j = Neo4jManager()
    return _neo4j


async def _hybrid_search(
    query: str, filters: dict[str, str], top_k: int = 5
) -> list[dict]:
    """Helper for hybrid searching Qdrant, with automatic tenant isolation."""
    embedder = get_embedder()
    vs = get_vector_store()
    branch = get_agent_branch_context()
    if branch and "branch" not in filters:
        filters = {**filters, "branch": branch}
    
    dense_vecs = await embedder.embed_batch([query])
    dense_vec = dense_vecs[0]
    sparse_vec = embedder.generate_sparse_vector(query)

    vs.ensure_collection()
    hits = vs.search(
        query_dense=dense_vec,
        query_sparse=sparse_vec,
        filters=filters,
        top_k=top_k,
        user_id=get_agent_user_context(),  # Tenant isolation
    )
    return hits


@tool
async def search_code(
    query: str,
    repo: str = Field(default=None, description="Repository name, e.g., 'owner/repo'"),
    language: str = Field(default=None, description="Programming language to filter by")
) -> str:
    """
    Search the codebase using semantic vector search.
    Best for finding implementations, feature definitions, business logic, or syntax.
    Returns the top matching code snippets showing file paths, function signatures, and code.
    """
    logger.info(f"Tool CALL: search_code(query='{query}', repo='{repo}')")
    filters = {"source_type": "code"}
    if repo:
        filters["repo"] = repo
    if language:
        filters["language"] = language

    hits = await _hybrid_search(query, filters=filters, top_k=5)
    if not hits:
        return f"No code found matching '{query}'. Note: search is scoped to repos you have access to."

    results = []
    for h in hits:
        p = h["payload"]
        results.append(
            f"FILE: {p.get('file_path')}\n"
            f"FUNCTION/CLASS: {p.get('function_name') or p.get('class_name') or 'N/A'}\n"
            f"LINES: {p.get('start_line')}-{p.get('end_line')}\n"
            f"SNIPPET:\n```\n{p.get('text')}\n```\n"
        )

    return "\n---\n".join(results)


@tool
async def search_issues(
    query: str,
    repo: str = Field(default=None, description="Repository name, e.g., 'owner/repo'"),
    state: str = Field(default=None, description="State to filter by: 'open' or 'closed'")
) -> str:
    """
    Search GitHub issues and pull requests semantically.
    Best for finding historical bugs, discussions, feature requests, or decisions.
    """
    logger.info(f"Tool CALL: search_issues(query='{query}', repo='{repo}')")
    
    filters = {}
    if repo:
        filters["repo"] = repo

    hits = await _hybrid_search(query, filters=filters, top_k=10)
    
    results = []
    for h in hits:
        p = h["payload"]
        stype = p.get("source_type")
        
        if stype not in ("issue", "pr"):
            continue
            
        p_state = p.get("state")
        if state and p_state != state:
            continue
            
        if stype == "issue":
            results.append(
                f"ISSUE #{p.get('issue_number')} ({p_state})\n"
                f"CONTENT: {p.get('text')[:300]}...\n"
            )
        else:
            results.append(
                f"PR #{p.get('pr_number')} ({p_state})\n"
                f"CONTENT: {p.get('text')[:300]}...\n"
            )

    if not results:
        return f"No issues/PRs found matching '{query}'"

    return "\n---\n".join(results[:5])


@tool
async def get_file_content(
    repo: str,
    file_path: str,
    mode: Literal["outline", "full"] = "outline"
) -> str:
    """
    Retrieve the content of a specific file from a specific repository.
    'outline' mode shows only class names, function signatures, and docstrings.
    'full' mode shows the entire file content (capped at 500 lines).
    """
    logger.info(f"Tool CALL: get_file_content(repo='{repo}', file='{file_path}', mode='{mode}')")
    vs = get_vector_store()
    filters = {"repo": repo, "file_path": file_path}
    
    vs.ensure_collection()
    dummy_dense = [0.0] * vs.dense_dim
    dummy_sparse = {"indices": [], "values": []}
    
    hits = vs.search(
        dummy_dense,
        dummy_sparse,
        filters=filters,
        top_k=200,
        user_id=get_agent_user_context(),
    )
    
    if not hits:
         return f"File '{file_path}' not found in index for {repo}."

    if mode == "outline":
        outline_parts = []
        code_chunks = [h["payload"] for h in hits if h["payload"].get("source_type") == "code"]
        code_chunks.sort(key=lambda x: x.get("start_line", 0) or 0)
        
        for p in code_chunks:
            ctype = p.get("chunk_type")
            sig = p.get("signature")
            if ctype in ("function", "method", "class"):
                outline_parts.append(f"- {ctype}: {sig} (Lines {p.get('start_line')}-{p.get('end_line')})")
        
        if not outline_parts:
            return f"File {file_path} exists but has no extractable code outline."
            
        return f"FILE OUTLINE for {file_path}:\n" + "\n".join(outline_parts)
    
    else: 
        code_chunks = [h["payload"] for h in hits if h["payload"].get("source_type") == "code"]
        code_chunks.sort(key=lambda x: x.get("start_line", 0) or 0)
        
        full_text_parts = []
        for p in code_chunks:
            full_text_parts.append(p.get("full_body") or p.get("text", ""))
            
        full_text = "\n\n".join(full_text_parts)
        
        lines = full_text.splitlines()
        if len(lines) > 500:
            lines = lines[:500]
            lines.append("... [TRUNCATED AT 500 LINES]")
            
        return "\n".join(lines)


@tool
def get_call_graph(function_name: str, repo: str | None = None) -> str:
    """
    Query the Neo4j Knowledge Graph to find what calls a function, and what the function calls.
    Returns callers (functions that call this one) and callees (functions this one calls).
    """
    logger.info(f"Tool CALL: get_call_graph(func='{function_name}', repo='{repo}')")
    neo4j = get_neo4j()
    user_id = get_agent_user_context()
    branch = get_agent_branch_context()
    callee_query = """
    MATCH (caller:Function {name: $func_name})-[:CALLS]->(callee:Function)
    """
    if repo:
        callee_query += " WHERE caller.repo = $repo AND callee.repo = $repo "
    else:
        callee_query += " WHERE true "
    if branch:
        callee_query += " AND coalesce(caller.branch, 'main') = $branch AND coalesce(callee.branch, 'main') = $branch "
    callee_query += " AND (caller.user_id = $user_id OR caller.is_public = true) AND (callee.user_id = $user_id OR callee.is_public = true) "
    callee_query += " RETURN callee.name AS callee_name, callee.repo AS repo LIMIT 20"
    
    callees = neo4j.run_query(callee_query, {"func_name": function_name, "repo": repo, "user_id": user_id, "branch": branch})
    
    caller_query = """
    MATCH (caller:Function)-[:CALLS]->(callee:Function {name: $func_name})
    """
    if repo:
         caller_query += " WHERE caller.repo = $repo AND callee.repo = $repo "
    else:
         caller_query += " WHERE true "
    if branch:
         caller_query += " AND coalesce(caller.branch, 'main') = $branch AND coalesce(callee.branch, 'main') = $branch "
    caller_query += " AND (caller.user_id = $user_id OR caller.is_public = true) AND (callee.user_id = $user_id OR callee.is_public = true) "
    caller_query += " RETURN caller.name AS caller_name, caller.repo AS repo LIMIT 20"
    
    callers = neo4j.run_query(caller_query, {"func_name": function_name, "repo": repo, "user_id": user_id, "branch": branch})
    
    if not callees and not callers:
        return f"No call graph data found for function '{function_name}'."
        
    res = f"Call Graph for {function_name}:\n\n"
    res += "- CALLERS (functions that call this):\n"
    for c in callers:
        res += f"  - {c['caller_name']} (in {c['repo']})\n"
    if not callers:
        res += "  (None found)\n"
        
    res += "\n- CALLEES (functions this calls):\n"
    for c in callees:
         res += f"  - {c['callee_name']} (in {c['repo']})\n"
    if not callees:
        res += "  (None found)\n"
        
    return res


@tool
def get_file_history(file_path: str, repo: str | None = None) -> str:
    """
    Query the Neo4j Knowledge Graph to find which PRs and Commits modified a file.
    Shows the Git history constraints and linked issues.
    """
    logger.info(f"Tool CALL: get_file_history(file='{file_path}')")
    neo4j = get_neo4j()
    user_id = get_agent_user_context()
    branch = get_agent_branch_context()
    query = """
    MATCH (f:File)
    WHERE f.path CONTAINS $file_path
    """
    if repo:
        query += " AND f.repo = $repo "
    if branch:
        query += " AND coalesce(f.branch, 'main') = $branch "
    query += " AND (f.user_id = $user_id OR f.is_public = true) "
        
    query += """
    OPTIONAL MATCH (pr:PullRequest)-[:MODIFIES]->(f)
    OPTIONAL MATCH (pr)-[:CLOSES]->(i:Issue)
    WHERE (pr.user_id = $user_id OR pr.is_public = true OR pr IS NULL)
    RETURN pr.number AS pr_num, pr.title AS pr_title, pr.state AS pr_state, i.number AS linked_issue
    ORDER BY pr.number DESC LIMIT 10
    """
    
    records = neo4j.run_query(query, {"file_path": file_path, "repo": repo, "user_id": user_id, "branch": branch})
    
    if not records or all(r['pr_num'] is None for r in records):
        return f"No PR history found for file containing '{file_path}'"
        
    res = f"History for file '{file_path}':\n"
    for r in records:
        if r['pr_num'] is not None:
             res += f"- PR #{r['pr_num']} ({r['pr_state']}): {r['pr_title']}"
             if r['linked_issue']:
                 res += f" (Closes Issue #{r['linked_issue']})"
             res += "\n"
             
    return res


@tool
def get_dependencies(module_name: str, repo: str | None = None) -> str:
    """
    Query the Neo4j Knowledge Graph to find what files import a module.
    Also queries generic dependencies declared in requirements.txt or package.json.
    """
    logger.info(f"Tool CALL: get_dependencies(module='{module_name}')")
    neo4j = get_neo4j()
    user_id = get_agent_user_context()
    branch = get_agent_branch_context()
    internal_query = """
    MATCH (file:File)-[:IMPORTS]->(mod:Module {name: $module_name})
    """
    if repo:
         internal_query += " WHERE file.repo = $repo "
    else:
         internal_query += " WHERE true "
    if branch:
         internal_query += " AND coalesce(file.branch, 'main') = $branch "
    internal_query += " AND (file.user_id = $user_id OR file.is_public = true) AND (mod.user_id = $user_id OR mod.is_public = true) "
    internal_query += " RETURN file.path AS file_path LIMIT 20"
    
    importers = neo4j.run_query(internal_query, {"module_name": module_name, "repo": repo, "user_id": user_id, "branch": branch})
    
    ext_query = """
    MATCH (r:Repository)-[:DEPENDS_ON]->(d:Dependency {name: $module_name})
    """
    if repo:
         ext_query += " WHERE r.full_name = $repo "
    else:
         ext_query += " WHERE true "
    if branch:
         ext_query += " AND coalesce(r.branch, 'main') = $branch "
    ext_query += " AND (r.user_id = $user_id OR r.is_public = true) AND (d.user_id = $user_id OR d.is_public = true) "
    ext_query += " RETURN d.version AS version LIMIT 1"
    
    deps = neo4j.run_query(ext_query, {"module_name": module_name, "repo": repo, "user_id": user_id, "branch": branch})
    
    res = f"Dependencies for '{module_name}':\n"
    if deps:
        res += f"- Resolved as external dependency (Version: {deps[0]['version']})\n"
        
    res += "- INTERNAL IMPORTERS (files that import this):\n"
    for i in importers:
        res += f"  - {i['file_path']}\n"
        
    if not importers and not deps:
         res += "  (None found)\n"
         
    return res


@tool
def calculate_math(expression: str) -> str:
    """
    Evaluate a mathematical expression safely. 
    Use this for simple arithmetic, comparisons, or ratio calculations.
    """
    logger.info(f"Tool CALL: calculate_math(expr='{expression}')")
    try:
        allowed_operators = {
            ast.Add: operator.add, ast.Sub: operator.sub,
            ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.Pow: operator.pow, ast.BitXor: operator.xor,
            ast.USub: operator.neg, ast.Mod: operator.mod
        }

        def eval_expr(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                return allowed_operators[type(node.op)](eval_expr(node.left), eval_expr(node.right))
            elif isinstance(node, ast.UnaryOp):
                return allowed_operators[type(node.op)](eval_expr(node.operand))
            else:
                raise TypeError(f"Unsupported node type: {type(node)}")

        parsed = ast.parse(expression, mode='eval').body
        result = eval_expr(parsed)
        return str(result)
    except Exception as e:
        return f"Error evaluating math: {str(e)}"


@tool
def ask_human_for_clarification(question: str) -> str:
    """
    Ask the user for clarification if the query is extremely ambiguous or lacks necessary parameters (like repo name).
    The Agent will automatically pause and return this to the user.
    """
    logger.info(f"Tool CALL: ask_human({question})")
    return f"CLARIFICATION REQUIRED: {question}"

# Export tool list for the agent
ALL_TOOLS = [
    search_code,
    search_issues,
    get_file_content,
    get_call_graph,
    get_file_history,
    get_dependencies,
    calculate_math,
    ask_human_for_clarification
]
