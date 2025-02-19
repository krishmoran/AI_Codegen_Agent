from typing import List, Dict, Optional, AsyncGenerator
import base64
from github import Github
from github.Repository import Repository
from github.ContentFile import ContentFile
import re
import asyncio
from datetime import datetime

class GitHubService:
    def __init__(self, github_token: str):
        """
        Initialize GitHub service.
        
        Args:
            github_token: GitHub personal access token
        """
        if not github_token:
            raise ValueError("GitHub token is required")
            
        self.github = Github(github_token)
        # Verify authentication
        try:
            user = self.github.get_user()
            print(f"\nAuthenticated as GitHub user: {user.login}")
        except Exception as e:
            print(f"Error authenticating with GitHub: {e}")
            raise

    def get_repository(self, owner: str, repo: str) -> Repository:
        """Get a GitHub repository."""
        try:
            repo_obj = self.github.get_repo(f"{owner}/{repo}")
            print(f"Successfully accessed repository: {repo_obj.full_name}")
            print(f"Default branch: {repo_obj.default_branch}")
            print(f"Private: {repo_obj.private}")
            return repo_obj
        except Exception as e:
            print(f"Error accessing repository {owner}/{repo}: {e}")
            raise

    async def get_default_branch(self, repo: Repository) -> str:
        """Get the default branch of a repository."""
        return repo.default_branch

    async def list_files(
        self,
        repo: Repository,
        path: str = "",
        ref: str = None,
        include_patterns: List[str] = None,
        exclude_patterns: List[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        List files in a repository that match the patterns.
        
        Args:
            repo: GitHub repository
            path: Path to list files from
            ref: Git reference (branch, tag, commit)
            include_patterns: List of glob patterns to include
            exclude_patterns: List of glob patterns to exclude
            
        Yields:
            File paths that match the patterns
        """
        print(f"\nListing files in {repo.full_name}")
        print(f"Path: {path}")
        print(f"Ref: {ref}")
        
        if include_patterns is None:
            include_patterns = ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx', '**/*.py']
        if exclude_patterns is None:
            exclude_patterns = ['**/node_modules/**', '**/dist/**', '**/.git/**']

        try:
            contents = repo.get_contents(path, ref=ref)
            print(f"Found {len(contents) if isinstance(contents, list) else 1} items")
        except Exception as e:
            print(f"Error getting contents: {e}")
            return

        while contents:
            content = contents.pop(0)
            if content.type == "dir":
                # Recursively get files from subdirectory
                async for file_path in self.list_files(
                    repo, content.path, ref, include_patterns, exclude_patterns
                ):
                    yield file_path
            else:
                # Check if file matches patterns
                file_path = content.path
                should_include = any(
                    (pattern.startswith('**/*.') and file_path.endswith(pattern.split('.')[-1])) or
                    (pattern.startswith('*.') and file_path.endswith(pattern.split('.')[-1])) or
                    file_path.endswith(pattern)
                    for pattern in include_patterns
                )
                should_exclude = any(
                    f'/{pattern.replace("**/", "").replace("/**", "")}/' in f'/{file_path}/'
                    for pattern in exclude_patterns
                )
                
                if should_include and not should_exclude:
                    print(f"Including file: {file_path}")
                    yield file_path
                else:
                    print(f"Skipping file: {file_path} (include={should_include}, exclude={not should_exclude})")

    async def get_file_content(
        self,
        repo: Repository,
        path: str,
        ref: str = None
    ) -> Optional[str]:
        """
        Get the content of a file from GitHub.
        
        Args:
            repo: GitHub repository
            path: Path to the file
            ref: Git reference (branch, tag, commit)
            
        Returns:
            File content as string
        """
        try:
            print(f"\nFetching content for: {path}")
            
            # Normalize path (remove backticks, leading/trailing slashes, normalize separators)
            normalized_path = path.strip('`').strip('/').replace('\\', '/')
            
            # Get rate limit info first
            rate_limit = self.github.get_rate_limit()
            print(f"Rate limit - Remaining: {rate_limit.core.remaining}/{rate_limit.core.limit}")
            
            if rate_limit.core.remaining <= 1:  # Leave 1 request as buffer
                print(f"Rate limit nearly exceeded. Resets at: {rate_limit.core.reset}")
                # Wait if reset is within next 5 minutes
                reset_in_seconds = (rate_limit.core.reset - datetime.now()).total_seconds()
                if reset_in_seconds <= 300:  # 5 minutes
                    print(f"Waiting {reset_in_seconds} seconds for rate limit reset...")
                    await asyncio.sleep(reset_in_seconds + 1)
                else:
                    return None
            
            # Try up to 3 times with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Use repo.get_contents() with normalized path
                    content_file = repo.get_contents(normalized_path, ref=ref or repo.default_branch)
                    
                    if content_file is None:
                        print(f"Error: No content found for {normalized_path}")
                        return None
                        
                    # Handle both single files and directories
                    if isinstance(content_file, list):
                        print(f"Error: Path {normalized_path} is a directory")
                        return None
                        
                    content = content_file.decoded_content.decode('utf-8')
                    print(f"Successfully decoded content, length: {len(content)}")
                    print(f"File type: {content_file.type}, size: {content_file.size} bytes")
                    return content
                    
                except Exception as e:
                    if "404" in str(e):
                        # Try with and without leading slash if 404
                        alt_path = f"/{normalized_path}" if not normalized_path.startswith('/') else normalized_path[1:]
                        try:
                            content_file = repo.get_contents(alt_path, ref=ref or repo.default_branch)
                            if content_file and not isinstance(content_file, list):
                                content = content_file.decoded_content.decode('utf-8')
                                print(f"Successfully retrieved content using alternative path: {alt_path}")
                                return content
                        except:
                            pass
                        
                        # If both attempts failed, try removing any remaining special characters
                        clean_path = re.sub(r'[^a-zA-Z0-9/._-]', '', normalized_path)
                        if clean_path != normalized_path:
                            try:
                                content_file = repo.get_contents(clean_path, ref=ref or repo.default_branch)
                                if content_file and not isinstance(content_file, list):
                                    content = content_file.decoded_content.decode('utf-8')
                                    print(f"Successfully retrieved content using cleaned path: {clean_path}")
                                    return content
                            except:
                                pass
                        
                        print(f"Error: File not found: {normalized_path}")
                        return None
                    elif "403" in str(e):
                        print(f"Error: Rate limit exceeded or authentication issue")
                        rate_limit = self.github.get_rate_limit()
                        print(f"Rate limit - Remaining: {rate_limit.core.remaining}/{rate_limit.core.limit}")
                        print(f"Resets at: {rate_limit.core.reset}")
                        
                        # Wait and retry if this is not the last attempt
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) * 5  # Exponential backoff: 5s, 10s, 20s
                            print(f"Waiting {wait_time} seconds before retry...")
                            await asyncio.sleep(wait_time)
                            continue
                        return None
                    else:
                        print(f"Error getting content of {normalized_path}: {str(e)}")
                        print(f"Error type: {type(e)}")
                        
                        # Wait and retry if this is not the last attempt
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt) * 5
                            print(f"Waiting {wait_time} seconds before retry...")
                            await asyncio.sleep(wait_time)
                            continue
                        return None
            
            return None
            
        except Exception as e:
            print(f"Unexpected error fetching {path}: {str(e)}")
            return None

    def _sanitize_branch_name(self, name: str) -> str:
        """Sanitize branch name to be valid for git."""
        # Replace spaces and special chars with hyphens
        sanitized = re.sub(r'[^a-zA-Z0-9-]', '-', name.lower())
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        return sanitized

    async def create_pull_request(
        self,
        repo: Repository,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        changes: List[Dict[str, str]]
    ) -> Optional[int]:
        """Create a pull request with the specified changes."""
        try:
            # Sanitize branch name
            head_branch = self._sanitize_branch_name(head_branch)
            print(f"Creating branch: {head_branch}")

            # Get the latest commit SHA of the base branch
            base_sha = repo.get_branch(base_branch).commit.sha
            
            # Create a new branch
            repo.create_git_ref(
                ref=f"refs/heads/{head_branch}",
                sha=base_sha
            )
            
            # Create commits with changes
            for change in changes:
                try:
                    path = change['path']
                    content = change['content']
                    
                    try:
                        # Try to get existing file
                        contents = repo.get_contents(path, ref=head_branch)
                        if isinstance(contents, list):
                            print(f"Skipping directory: {path}")
                            continue
                        
                        # Update existing file
                        print(f"Updating file: {path}")
                        repo.update_file(
                            path=path,
                            message=f"Update {path}",
                            content=content,
                            sha=contents.sha,
                            branch=head_branch
                        )
                    except Exception as e:
                        if "404" in str(e):  # File not found
                            # Create new file
                            print(f"Creating new file: {path}")
                            repo.create_file(
                                path=path,
                                message=f"Create {path}",
                                content=content,
                                branch=head_branch
                            )
                        else:
                            raise  # Re-raise other exceptions
                except Exception as e:
                    print(f"Error processing file {change.get('path')}: {e}")
                    raise
            
            # Create pull request
            pr = repo.create_pull(
                title=title,
                body=body,
                head=head_branch,
                base=base_branch
            )
            
            return pr.number
        except Exception as e:
            print(f"Error creating pull request: {e}")
            return None 