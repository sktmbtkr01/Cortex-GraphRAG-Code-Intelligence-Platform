"""
Cortex Graph Static Analyzer
Parses code files natively without an LLM to extract dependency graphs,
import hierarchies, function calls, and class inheritances.
"""

import ast
import json
import re
from typing import List

from core.logger import get_logger

logger = get_logger(__name__)


# Standard library approximation for Python 3.12
PYTHON_STDLIB = {
    "os", "sys", "re", "json", "ast", "math", "datetime", "typing", "collections",
    "itertools", "functools", "pathlib", "logging", "asyncio", "hashlib", "time",
    "uuid", "subprocess", "random", "urllib", "threading", "queue", "concurrent",
    "unittest", "pytest", "argparse", "sqlite3", "csv", "xml", "html", "http",
    "socket", "ssl", "email", "base64", "configparser", "contextlib", "copy",
}


class NodeEdgeExtractor:
    """Extracts graph edges from source code and dependency manifests."""
    
    @staticmethod
    def extract_python_edges(file_path: str, repo: str, source: str) -> list[dict]:
        """
        Uses Python's native AST module to deeply parse the target file.
        Returns a list of edge dictionaries to be merged into Neo4j.
        """
        edges = []
        file_id = f"{repo}::{file_path}"
        
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Skip invalid Python files gracefully
            return edges

        for node in ast.walk(tree):
            # 1. Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split('.')[0]
                    mod_type = "stdlib" if module_name in PYTHON_STDLIB else "third-party"
                    edges.append({
                        "from_label": "File", "from_id": file_id,
                        "to_label": "Module", "to_id": f"python::{module_name}",
                        "rel_type": "IMPORTS",
                        "properties": {"ecosystem": "pip", "type": mod_type}
                    })
                    
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Internal imports usually have a dot level or match project structure
                    is_local = node.level > 0
                    mod_name = node.module.split('.')[0]
                    
                    if is_local:
                        # Map to presumed file path
                        target_file_id = f"{repo}::{node.module.replace('.', '/')}"
                        edges.append({
                            "from_label": "File", "from_id": file_id,
                            "to_label": "File", "to_id": target_file_id,
                            "rel_type": "IMPORTS",
                            "properties": {"type": "local"}
                        })
                    else:
                        mod_type = "stdlib" if mod_name in PYTHON_STDLIB else "third-party"
                        edges.append({
                            "from_label": "File", "from_id": file_id,
                            "to_label": "Module", "to_id": f"python::{mod_name}",
                            "rel_type": "IMPORTS",
                            "properties": {"ecosystem": "pip", "type": mod_type}
                        })

            # 2. Class Definitions & Inheritance
            elif isinstance(node, ast.ClassDef):
                class_id = f"{file_id}::class::{node.name}"
                edges.append({
                    "from_label": "Class", "from_id": class_id,
                    "to_label": "File", "to_id": file_id,
                    "rel_type": "DEFINED_IN"
                })
                
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        parent_class_id = f"{file_id}::class::{base.id}"
                        edges.append({
                            "from_label": "Class", "from_id": class_id,
                            "to_label": "Class", "to_id": parent_class_id,
                            "rel_type": "INHERITS_FROM"
                        })

            # 3. Function Definitions
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_id = f"{file_id}::func::{node.name}"
                edges.append({
                    "from_label": "Function", "from_id": func_id,
                    "to_label": "File", "to_id": file_id,
                    "rel_type": "DEFINED_IN"
                })
                
                # We could extract function calls internally here by walking the function body 
                # looking for ast.Call, but for graph brevity we limit caller tracking to 
                # high-confidence internal module calls.
                for child in ast.walk(node):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                        callee_name = child.func.id
                        callee_id = f"{file_id}::func::{callee_name}"
                        edges.append({
                            "from_label": "Function", "from_id": func_id,
                            "to_label": "Function", "to_id": callee_id,
                            "rel_type": "CALLS"
                        })

        return edges

    @staticmethod
    def extract_js_ts_edges(file_path: str, repo: str, source: str) -> list[dict]:
        """
        Uses regex block parsing to extract imports for TS/JS.
        Regex handles string-based matching since JS ASTs require Node.js runtimes.
        """
        edges = []
        file_id = f"{repo}::{file_path}"
        
        # Matches: import { X } from 'target' OR import 'target'
        import_pattern = re.compile(r"import\s+(?:.*from\s+)?['\"]([^'\"]+)['\"]")
        # Matches: require('target')
        require_pattern = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")

        targets = import_pattern.findall(source) + require_pattern.findall(source)
        
        for target in targets:
            if target.startswith('.') or target.startswith('/'):
                # Local file import
                target_file_id = f"{repo}::{target}"
                edges.append({
                    "from_label": "File", "from_id": file_id,
                    "to_label": "File", "to_id": target_file_id,
                    "rel_type": "IMPORTS",
                    "properties": {"type": "local"}
                })
            else:
                # Third-party npm package
                edges.append({
                    "from_label": "File", "from_id": file_id,
                    "to_label": "Module", "to_id": f"npm::{target}",
                    "rel_type": "IMPORTS",
                    "properties": {"ecosystem": "npm", "type": "third-party"}
                })
                
        return edges

    @staticmethod
    def parse_manifest(file_path: str, repo: str, content: str) -> list[dict]:
        """
        Parses `package.json`, `requirements.txt`, or `go.mod`
        Returns repository-level dependencies.
        """
        edges = []
        repo_id = repo
        
        if file_path.endswith("package.json"):
            try:
                data = json.loads(content)
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                
                for dep, ver in {**deps, **dev_deps}.items():
                    edges.append({
                        "from_label": "Repository", "from_id": repo_id,
                        "to_label": "Dependency", "to_id": f"npm::{dep}::{ver}",
                        "rel_type": "DEPENDS_ON",
                        "properties": {"ecosystem": "npm", "name": dep, "version": ver}
                    })
            except json.JSONDecodeError:
                pass

        elif file_path.endswith("requirements.txt"):
            lines = content.split('\n')
            for line in lines:
                line = line.split('#')[0].strip()
                if not line:
                    continue
                # matches requests==2.31.0 or just requests
                match = re.match(r'^([a-zA-Z0-9_\-]+)[=<>~\^]*(.*)', line)
                if match:
                    dep = match.group(1).strip()
                    ver = match.group(2).strip() or "latest"
                    edges.append({
                        "from_label": "Repository", "from_id": repo_id,
                        "to_label": "Dependency", "to_id": f"pip::{dep}::{ver}",
                        "rel_type": "DEPENDS_ON",
                        "properties": {"ecosystem": "pip", "name": dep, "version": ver}
                    })

        return edges
