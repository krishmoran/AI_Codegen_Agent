from typing import List, Dict, Optional, Literal
from dataclasses import dataclass
import asyncio
from openai import AsyncOpenAI
from .types import FileChange
from .codebase import CodebaseUnderstanding
from .config import ServiceConfig
import re

@dataclass
class FileChangeWithType:
    file: str
    content: str
    change_type: Literal['create', 'modify']
    original_content: Optional[str] = None
    insert_after_line: Optional[int] = None

class CodeGenerator:
    def __init__(self, config: ServiceConfig, codebase: CodebaseUnderstanding):
        """
        Initialize code generator.
        
        Args:
            config: Service configuration
            codebase: Codebase understanding instance
        """
        self.config = config
        self.codebase = codebase
        self.openai = AsyncOpenAI(api_key=config.openai_api_key)

    async def _get_existing_files(self) -> List[str]:
        """Get list of existing files in the repository."""
        try:
            files = []
            # Get default branch
            branch = await self.codebase.github.get_default_branch(self.codebase.repo)
            
            # Let github_service use its default patterns
            async for file_path in self.codebase.github.list_files(
                self.codebase.repo,
                ref=branch
            ):
                files.append(file_path)
            return files
        except Exception as e:
            print(f"Warning: Error getting existing files: {e}")
            return []

    async def _get_file_content(self, file_path: str) -> Optional[str]:
        """Get content of an existing file."""
        try:
            return await self.codebase.github.get_file_content(self.codebase.repo, file_path)
        except:
            return None

    def _clean_file_path(self, path: str) -> str:
        """Clean and normalize a file path from LLM response."""
        # Remove backticks, markdown formatting, etc.
        cleaned = path.strip('`').strip()
        # Normalize slashes
        cleaned = cleaned.replace('\\', '/')
        # Remove any remaining special characters except common path chars
        cleaned = re.sub(r'[^a-zA-Z0-9/._-]', '', cleaned)
        return cleaned

    async def generate_implementation(
        self,
        description: str,
        context_query: Optional[str] = None,
        max_files: int = 5
    ) -> List[FileChangeWithType]:
        """
        Generate code implementation from description.
        
        Args:
            description: Natural language description of the changes
            context_query: Optional query to find relevant code context
            max_files: Maximum number of files to modify
            
        Returns:
            List of file changes
        """
        # Get existing files first
        existing_files = await self._get_existing_files()
        print(f"\nFound {len(existing_files)} existing files in repository")

        # Get relevant code context if query provided
        context_items = []
        if context_query:
            context_items = await self.codebase.search_similar_code(
                query=context_query,
                n_results=3
            )
        
        context_str = "\n\n".join([
            f"File: {item.name}\n{item.content}"
            for item in context_items
        ])

        # Generate implementation plan
        plan_prompt = f"""Given the following task description and code context, create a detailed plan for implementing the changes.

        Important Guidelines:
        1. Consider the complete dependency chain - identify ALL files that need to be created or modified
        2. Order changes from most fundamental to dependent (e.g., types/interfaces before their implementations)
        3. Consider shared utilities, helpers, or types that might be needed
        4. Think about where new code best fits in the existing structure
        5. Consider configuration changes if needed (e.g., new dependencies, environment variables)
        6. IMPORTANT: Check if files already exist before creating new ones
           Existing files: {existing_files}

        Task Description:
        {description}

        Relevant Code Context:
        {context_str if context_str else 'No context provided'}

        Provide your response in the following format:
        1. List all required files in order:
           FILE: <file_path>
           ACTION: create|modify
           PURPOSE: <why this file is needed>
           DEPENDS_ON: <any files this depends on>
           CHANGES: <for modify actions, describe what needs to change>

        2. Additional context or considerations
        """

        plan_response = await self.openai.chat.completions.create(
            model=self.config.completion_model,
            messages=[{"role": "user", "content": plan_prompt}]
        )
        implementation_plan = plan_response.choices[0].message.content

        # Parse the plan to get list of files and their actions
        planned_files = []
        file_actions = {}  # Track whether each file should be created or modified
        current_file = None
        for line in implementation_plan.split('\n'):
            line = line.strip()
            if line.startswith('FILE:'):
                current_file = self._clean_file_path(line.split('FILE:')[1].strip())
                planned_files.append(current_file)
            elif line.startswith('ACTION:') and current_file:
                file_actions[current_file] = line.split('ACTION:')[1].strip()

        print(f"\nPlanned files: {[f'{f} ({file_actions.get(f, "unknown")})' for f in planned_files]}")

        # Generate actual code changes
        changes = []
        remaining_files = set(planned_files)

        while remaining_files and len(changes) < max_files:
            file_to_change = next(iter(remaining_files))
            is_new_file = file_actions.get(file_to_change) == 'create'
            existing_content = None if is_new_file else await self._get_file_content(file_to_change)

            code_prompt = f"""Based on the implementation plan and code context, generate the next file change.
            
            File to change: {file_to_change}
            Action: {file_actions.get(file_to_change, 'unknown')}
            Existing content: {existing_content if existing_content else 'New file'}
            
            Files already created: {', '.join(c.file for c in changes)}
            Files still needed: {', '.join(remaining_files)}
            Existing repository files: {existing_files}

            Implementation Plan:
            {implementation_plan}

            Code Context:
            {context_str if context_str else 'No context provided'}

            Important Guidelines:
            1. Generate complete, self-contained code that handles all dependencies
            2. If this file requires new dependencies:
               - Create/modify any necessary configuration files
               - Add required package dependencies
               - Create any shared types, utilities, or helpers needed
            3. Follow the existing codebase patterns and style
            4. Include all necessary imports and references
            5. Consider error handling and edge cases
            6. Add appropriate documentation and comments
            7. For existing files, only generate the specific changes needed

            For new files, provide complete file content.
            For existing files, provide only the new/modified content and where to insert it.
            
            Provide your response in the following format:
            FILE: <file_path>
            ACTION: create|modify
            INSERT_AFTER_LINE: <line number, only for modify>
            CONTENT:
            <content>
            END_CONTENT
            """

            code_response = await self.openai.chat.completions.create(
                model=self.config.completion_model,
                messages=[{"role": "user", "content": code_prompt}]
            )
            
            response_text = code_response.choices[0].message.content
            
            # Parse response
            if "FILE:" not in response_text or "CONTENT:" not in response_text:
                print(f"Warning: Invalid response format, skipping")
                continue
                
            file_path = self._clean_file_path(response_text.split("FILE:")[1].split("\n")[0].strip())
            action = response_text.split("ACTION:")[1].split("\n")[0].strip()
            insert_after_line = None
            
            # Extract content first
            content_parts = response_text.split("CONTENT:")[1].split("END_CONTENT")[0].strip().split("\n")
            
            # Look for INSERT_AFTER_LINE directive in the first few lines
            for i, line in enumerate(content_parts):
                if line.strip().startswith("INSERT_AFTER_LINE:"):
                    try:
                        insert_after_line = int(line.strip().split("INSERT_AFTER_LINE:")[1].strip())
                        # Remove the directive line from content
                        content_parts.pop(i)
                    except:
                        pass
                    break
            
            content = "\n".join(content_parts).strip()
            
            if file_path in remaining_files:
                remaining_files.remove(file_path)
            
            changes.append(FileChangeWithType(
                file=file_path,
                content=content,
                change_type=action,
                original_content=existing_content,
                insert_after_line=insert_after_line if action == 'modify' else None
            ))
            print(f"Generated {'changes for' if action == 'modify' else ''} file {file_path}, {len(remaining_files)} files remaining")

        if remaining_files:
            print(f"Warning: Some planned files were not created: {remaining_files}")

        return changes

    async def create_pr_from_description(
        self,
        description: str,
        context_query: Optional[str] = None,
        base_branch: Optional[str] = None
    ) -> Optional[int]:
        """
        Create a pull request from a natural language description.
        
        Args:
            description: Natural language description of the changes
            context_query: Optional query to find relevant code context
            base_branch: Base branch for the PR
            
        Returns:
            PR number if successful
        """
        # Generate code changes
        changes = await self.generate_implementation(description, context_query)
        
        if not changes:
            return None
            
        # Convert FileChangeWithType to regular FileChange for analysis
        simple_changes = []
        for change in changes:
            if change.change_type == 'create':
                simple_changes.append(FileChange(file=change.file, content=change.content))
            else:
                # For modifications, we need to apply the changes to the original content
                if change.original_content and change.insert_after_line:
                    lines = change.original_content.splitlines()
                    new_lines = lines[:change.insert_after_line]
                    new_lines.extend(change.content.splitlines())
                    new_lines.extend(lines[change.insert_after_line:])
                    simple_changes.append(FileChange(file=change.file, content='\n'.join(new_lines)))
                else:
                    # Fallback to full content if we can't do partial update
                    simple_changes.append(FileChange(file=change.file, content=change.content))
            
        # Analyze changes
        analysis = await self.codebase.analyze_changes(simple_changes)
        
        # Generate PR description
        pr_description = f"""🤖 This PR was automatically generated by AI

## Description
{description}

## Changes Made

### Files Created
{'\n'.join(f'- `{c.file}` - New file' for c in changes if c.change_type == 'create')}

### Files Modified
{'\n'.join(f'- `{c.file}` - Updated' for c in changes if c.change_type == 'modify')}

"""

        # Create PR
        pr_number = await self.codebase.create_pull_request(
            title=f"[AI-CODEGEN-TEST] {description.split('\n')[0][:50]}",  # Use first line as title
            description=pr_description,
            changes=simple_changes,
            base_branch=base_branch
        )
        
        return pr_number 