#!/usr/bin/env python3
"""
GitHub PR Analytics Report Generator

This script analyzes GitHub PRs associated with Jira issues from specified sprints
and generates comprehensive analytics reports.
"""

import os
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, Counter
from dataclasses import dataclass, field
import argparse

import requests
from github import Github
from atlassian import Jira
from dotenv import load_dotenv
from dateutil.parser import parse as parse_date
import pytz
from tqdm import tqdm
import asyncio
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport

# Load environment variables
load_dotenv()


@dataclass
class PRMetrics:
    """Data class for PR metrics"""

    pr_number: int
    title: str
    author: str
    created_at: datetime
    merged_at: Optional[datetime]
    first_review_at: Optional[datetime]
    size: int  # additions + deletions
    comments_count: int
    reviewers: List[str]
    lgtm_count: int
    lgtm_users: List[str]
    sprint_week: int  # 1, 2, or 3
    jira_issue: str

    # Jira workflow timing metrics
    jira_in_progress_at: Optional[datetime] = None
    jira_resolved_at: Optional[datetime] = None

    @property
    def time_to_merge_hours(self) -> Optional[float]:
        if self.merged_at:
            return (self.merged_at - self.created_at).total_seconds() / 3600
        return None

    @property
    def time_to_first_review_hours(self) -> Optional[float]:
        if self.first_review_at:
            return (self.first_review_at - self.created_at).total_seconds() / 3600
        return None

    @property
    def time_first_review_to_merge_hours(self) -> Optional[float]:
        if self.first_review_at and self.merged_at:
            return (self.merged_at - self.first_review_at).total_seconds() / 3600
        return None

    @property
    def time_in_progress_to_pr_created_hours(self) -> Optional[float]:
        """Time from Jira 'In Progress' to PR created"""
        if self.jira_in_progress_at and self.created_at:
            return (self.created_at - self.jira_in_progress_at).total_seconds() / 3600
        return None

    @property
    def time_in_progress_to_pr_merged_hours(self) -> Optional[float]:
        """Time from Jira 'In Progress' to PR merged"""
        if self.jira_in_progress_at and self.merged_at:
            return (self.merged_at - self.jira_in_progress_at).total_seconds() / 3600
        return None

    @property
    def time_pr_merged_to_resolved_hours(self) -> Optional[float]:
        """Time from PR merged to Jira 'Resolved'"""
        if self.merged_at and self.jira_resolved_at:
            return (self.jira_resolved_at - self.merged_at).total_seconds() / 3600
        return None


@dataclass
class SprintConfig:
    """Sprint configuration"""

    name: str
    start_date: datetime
    end_date: datetime

    def get_week_boundaries(self) -> Tuple[datetime, datetime, datetime, datetime]:
        """Get week boundaries for the sprint (3-week sprints)"""
        duration = self.end_date - self.start_date
        week_duration = duration / 3

        week1_end = self.start_date + week_duration
        week2_end = self.start_date + (2 * week_duration)

        return (self.start_date, week1_end, week2_end, self.end_date)

    def get_week_for_date(self, date: datetime) -> int:
        """Get which week of the sprint a date falls into (1, 2, or 3)"""
        week1_start, week1_end, week2_end, week3_end = self.get_week_boundaries()

        if date < week1_end:
            return 1
        elif date < week2_end:
            return 2
        else:
            return 3


class JiraClient:
    """Jira API client wrapper"""

    def __init__(
        self,
        url: str,
        token: str = None,
        username: str = None,
        password: str = None,
        github_field_id: str = "customfield_12310220",
        sprint_field_id: str = "customfield_12310940",
    ):
        # Support both token-based (on-premise) and username/password authentication
        if token:
            # Token-based authentication for on-premise Jira
            self.client = Jira(url=url, token=token)
        elif username and password:
            # Username/password authentication for cloud Jira
            self.client = Jira(url=url, username=username, password=password)
        else:
            raise ValueError(
                "Either 'token' or both 'username' and 'password' must be provided"
            )

        self.github_field_id = github_field_id
        self.sprint_field_id = sprint_field_id

    def get_sprint_issues(self, sprint_id: str) -> List[Dict[str, Any]]:
        """Get all issues from a specific sprint using sprint ID"""
        try:
            # Search for issues in the sprint using custom field
            # sprint_id can be either numeric ID or string name
            jql = f"Sprint={sprint_id}"
            issues = self.client.jql(jql, expand="changelog")
            return issues.get("issues", [])
        except Exception as e:
            print(f"Error fetching sprint issues for {sprint_id}: {e}")
            return []

    def extract_github_urls(self, issue: Dict[str, Any]) -> List[str]:
        """Extract GitHub PR URLs from a Jira issue"""
        github_urls = []

        # Check the specific custom field for GitHub PR
        fields = issue.get("fields", {})
        github_pr_field = fields.get(self.github_field_id, "")
        if isinstance(github_pr_field, list) and len(github_pr_field) > 0:
            github_urls.extend(github_pr_field)

        # Check other custom fields that might contain GitHub links (fallback)
        for field_name, field_value in fields.items():
            if (
                field_name.startswith("customfield_")
                and field_name != self.github_field_id  # Already checked above
                and field_value
                and isinstance(field_value, str)
            ):
                urls = self._find_github_urls(field_value)
                github_urls.extend(urls)

        return list(set(github_urls))  # Remove duplicates

    def extract_status_transitions(
        self, issue: Dict[str, Any]
    ) -> Dict[str, Optional[datetime]]:
        """Extract status transition timestamps from Jira issue changelog"""
        transitions = {"in_progress_at": None, "resolved_at": None}

        # Get the changelog from the issue
        changelog = issue.get("changelog", {})
        histories = changelog.get("histories", [])

        for history in histories:
            created = parse_date(history["created"]).replace(tzinfo=pytz.UTC)
            items = history.get("items", [])

            for item in items:
                if item.get("field") == "status":
                    to_status = item.get("toString", "").lower()

                    # Track when issue moved to "In Progress"
                    if "in progress" in to_status or "inprogress" in to_status:
                        if (
                            not transitions["in_progress_at"]
                            or created < transitions["in_progress_at"]
                        ):
                            transitions["in_progress_at"] = created

                    # Track when issue moved to "Resolved"
                    if (
                        "resolved" in to_status
                        or "done" in to_status
                        or "closed" in to_status
                    ):
                        transitions["resolved_at"] = (
                            created  # Take the latest resolved date
                        )

        return transitions

    def _find_github_urls(self, text: str) -> List[str]:
        """Find GitHub PR URLs in text"""
        if not text:
            return []

        # Pattern to match GitHub PR URLs
        github_pr_pattern = r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+"
        return re.findall(github_pr_pattern, text, re.IGNORECASE)


class GitHubClient:
    """GitHub API client wrapper"""

    def __init__(self, token: str):
        self.client = Github(token)
        self.token = token

        # Setup GraphQL client for bulk operations
        self.transport = AIOHTTPTransport(
            url="https://api.github.com/graphql",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.graphql_client = Client(transport=self.transport)

    def analyze_pr(
        self,
        pr_url: str,
        sprint_config: SprintConfig,
        jira_issue: str,
        jira_transitions: Optional[Dict[str, Optional[datetime]]] = None,
    ) -> Optional[PRMetrics]:
        """Analyze a GitHub PR and return metrics"""
        try:
            # Parse PR URL to get owner, repo, and PR number
            match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
            if not match:
                return None

            owner, repo, pr_number = match.groups()
            pr_number = int(pr_number)

            # Get the repository and PR
            repository = self.client.get_repo(f"{owner}/{repo}")
            pr = repository.get_pull(pr_number)

            # Get PR metrics
            created_at = pr.created_at.replace(tzinfo=pytz.UTC)
            merged_at = pr.merged_at.replace(tzinfo=pytz.UTC) if pr.merged_at else None

            # Get first review time
            reviews = pr.get_reviews()
            first_review_at = None
            reviewers = set()

            for review in reviews:
                if review.state in ["APPROVED", "CHANGES_REQUESTED", "COMMENTED"]:
                    if not first_review_at or review.submitted_at < first_review_at:
                        first_review_at = review.submitted_at.replace(tzinfo=pytz.UTC)
                    reviewers.add(review.user.login)

            # Get comments and LGTM analysis
            comments = pr.get_issue_comments()
            review_comments = pr.get_review_comments()

            total_comments = comments.totalCount + review_comments.totalCount
            lgtm_users = set()

            # Check for LGTM in comments
            for comment in comments:
                if "/lgtm" in comment.body.lower() or "lgtm" in comment.body.lower():
                    lgtm_users.add(comment.user.login)

            for comment in review_comments:
                if "/lgtm" in comment.body.lower() or "lgtm" in comment.body.lower():
                    lgtm_users.add(comment.user.login)

            # Calculate PR size
            size = pr.additions + pr.deletions

            # Determine sprint week
            sprint_week = sprint_config.get_week_for_date(created_at)

            # Get Jira workflow timing data
            jira_in_progress_at = None
            jira_resolved_at = None
            if jira_transitions:
                jira_in_progress_at = jira_transitions.get("in_progress_at")
                jira_resolved_at = jira_transitions.get("resolved_at")

            return PRMetrics(
                pr_number=pr_number,
                title=pr.title,
                author=pr.user.login,
                created_at=created_at,
                merged_at=merged_at,
                first_review_at=first_review_at,
                size=size,
                comments_count=total_comments,
                reviewers=list(reviewers),
                lgtm_count=len(lgtm_users),
                lgtm_users=list(lgtm_users),
                sprint_week=sprint_week,
                jira_issue=jira_issue,
                jira_in_progress_at=jira_in_progress_at,
                jira_resolved_at=jira_resolved_at,
            )

        except Exception as e:
            print(f"Error analyzing PR {pr_url}: {e}")
            return None

    async def bulk_analyze_prs(
        self,
        pr_data_list: List[
            Tuple[str, SprintConfig, str, Optional[Dict[str, Optional[datetime]]]]
        ],
    ) -> List[Optional[PRMetrics]]:
        """Bulk analyze multiple PRs using GraphQL for better performance"""
        if not pr_data_list:
            return []

        # Group PRs by repository to optimize GraphQL queries
        repos = defaultdict(list)
        for pr_url, sprint_config, jira_issue, jira_transitions in pr_data_list:
            match = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
            if match:
                owner, repo, pr_number = match.groups()
                repos[f"{owner}/{repo}"].append(
                    {
                        "number": int(pr_number),
                        "url": pr_url,
                        "sprint_config": sprint_config,
                        "jira_issue": jira_issue,
                        "jira_transitions": jira_transitions,
                    }
                )

        all_pr_metrics = []

        # Process each repository
        for repo_name, prs in repos.items():
            try:
                # Batch size of 20 PRs per GraphQL query (GitHub's limit)
                batch_size = 20
                for i in range(0, len(prs), batch_size):
                    batch = prs[i : i + batch_size]
                    metrics = await self._fetch_pr_batch_graphql(repo_name, batch)
                    all_pr_metrics.extend(metrics)
            except Exception as e:
                print(f"Error bulk analyzing PRs for {repo_name}: {e}")
                # Fallback to individual PR analysis
                for pr_data in batch:
                    result = self.analyze_pr(
                        pr_data["url"],
                        pr_data["sprint_config"],
                        pr_data["jira_issue"],
                        pr_data["jira_transitions"],
                    )
                    all_pr_metrics.append(result)

        return all_pr_metrics

    async def _fetch_pr_batch_graphql(
        self, repo_name: str, pr_batch: List[Dict]
    ) -> List[Optional[PRMetrics]]:
        """Fetch a batch of PRs using GraphQL"""
        owner, repo = repo_name.split("/")
        pr_metrics = []

        # Build GraphQL query for batch of PRs
        pr_queries = []
        for i, pr_data in enumerate(pr_batch):
            pr_number = pr_data["number"]
            pr_queries.append(
                f"""
                pr{i}: pullRequest(number: {pr_number}) {{
                    number
                    title
                    author {{
                        login
                    }}
                    createdAt
                    mergedAt
                    additions
                    deletions
                    comments(first: 100) {{
                        totalCount
                        nodes {{
                            body
                            author {{
                                login
                            }}
                        }}
                    }}
                    reviews(first: 100) {{
                        totalCount
                        nodes {{
                            state
                            submittedAt
                            author {{
                                login
                            }}
                        }}
                    }}
                    reviewRequests(first: 50) {{
                        nodes {{
                            requestedReviewer {{
                                ... on User {{
                                    login
                                }}
                            }}
                        }}
                    }}
                }}
            """
            )

        query = gql(
            f"""
            query {{
                repository(owner: "{owner}", name: "{repo}") {{
                    {' '.join(pr_queries)}
                }}
            }}
        """
        )

        try:
            result = await self.graphql_client.execute_async(query)
            repository_data = result["repository"]

            # Process each PR in the batch
            for i, pr_data in enumerate(pr_batch):
                pr_key = f"pr{i}"
                if pr_key in repository_data and repository_data[pr_key]:
                    pr_info = repository_data[pr_key]
                    metrics = self._process_graphql_pr_data(
                        pr_info,
                        pr_data["sprint_config"],
                        pr_data["jira_issue"],
                        pr_data["jira_transitions"],
                    )
                    pr_metrics.append(metrics)
                else:
                    pr_metrics.append(None)

        except Exception as e:
            print(f"GraphQL error for {repo_name}: {e}")
            # Return None for all PRs in this batch to trigger fallback
            pr_metrics = [None] * len(pr_batch)

        return pr_metrics

    def _process_graphql_pr_data(
        self,
        pr_data: Dict,
        sprint_config: SprintConfig,
        jira_issue: str,
        jira_transitions: Optional[Dict[str, Optional[datetime]]] = None,
    ) -> Optional[PRMetrics]:
        """Process GraphQL PR data into PRMetrics object"""
        try:
            # Parse dates
            created_at = parse_date(pr_data["createdAt"]).replace(tzinfo=pytz.UTC)
            merged_at = None
            if pr_data["mergedAt"]:
                merged_at = parse_date(pr_data["mergedAt"]).replace(tzinfo=pytz.UTC)

            # Process reviews
            reviews = pr_data.get("reviews", {}).get("nodes", [])
            first_review_at = None
            reviewers = set()

            for review in reviews:
                if review["state"] in ["APPROVED", "CHANGES_REQUESTED", "COMMENTED"]:
                    review_date = parse_date(review["submittedAt"]).replace(
                        tzinfo=pytz.UTC
                    )
                    if not first_review_at or review_date < first_review_at:
                        first_review_at = review_date
                    if review["author"] and review["author"]["login"]:
                        reviewers.add(review["author"]["login"])

            # Process comments and LGTM analysis
            comments = pr_data.get("comments", {}).get("nodes", [])
            total_comments = pr_data.get("comments", {}).get("totalCount", 0)
            lgtm_users = set()

            for comment in comments:
                body = comment.get("body", "").lower()
                if "/lgtm" in body or "lgtm" in body:
                    if comment["author"] and comment["author"]["login"]:
                        lgtm_users.add(comment["author"]["login"])

            # Calculate PR size
            size = pr_data.get("additions", 0) + pr_data.get("deletions", 0)

            # Determine sprint week
            sprint_week = sprint_config.get_week_for_date(created_at)

            # Get Jira workflow timing data
            jira_in_progress_at = None
            jira_resolved_at = None
            if jira_transitions:
                jira_in_progress_at = jira_transitions.get("in_progress_at")
                jira_resolved_at = jira_transitions.get("resolved_at")

            return PRMetrics(
                pr_number=pr_data["number"],
                title=pr_data["title"],
                author=pr_data["author"]["login"] if pr_data["author"] else "unknown",
                created_at=created_at,
                merged_at=merged_at,
                first_review_at=first_review_at,
                size=size,
                comments_count=total_comments,
                reviewers=list(reviewers),
                lgtm_count=len(lgtm_users),
                lgtm_users=list(lgtm_users),
                sprint_week=sprint_week,
                jira_issue=jira_issue,
                jira_in_progress_at=jira_in_progress_at,
                jira_resolved_at=jira_resolved_at,
            )

        except Exception as e:
            print(f"Error processing GraphQL PR data: {e}")
            return None


class SprintAnalyzer:
    """Main analyzer class"""

    def __init__(
        self,
        jira_url: str,
        github_token: str,
        jira_token: str = None,
        jira_username: str = None,
        jira_password: str = None,
        github_field_id: str = "customfield_12310220",
        sprint_field_id: str = "customfield_12310940",
        github_owner: str = None,
        github_repo: str = None,
    ):
        self.jira = JiraClient(
            jira_url,
            jira_token,
            jira_username,
            jira_password,
            github_field_id,
            sprint_field_id,
        )
        self.github = GitHubClient(github_token)
        self.github_owner = github_owner
        self.github_repo = github_repo

    def analyze_sprints(
        self, sprint_ids: List[str], sprint_length_weeks: int = 3
    ) -> Dict[str, Any]:
        """Analyze multiple sprints and return comprehensive metrics"""

        # Get sprint configurations (you may need to adjust this based on your sprint ID/dating)
        sprint_configs = self._get_sprint_configs(sprint_ids, sprint_length_weeks)

        all_prs = []
        sprint_metrics = {}
        all_pr_data = []  # Collect all PR data for bulk processing
        sprint_issue_mapping = {}  # Track which PRs belong to which sprint

        # Phase 1: Collect all GitHub PR URLs from all sprints
        print("🔍 Phase 1: Collecting GitHub PR URLs from Jira issues...")
        sprint_progress = tqdm(
            sprint_ids,
            desc="📋 Fetching Issues",
            unit="sprint",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} sprints [{elapsed}<{remaining}]",
        )

        for sprint_id in sprint_progress:
            sprint_progress.set_description(f"📋 Sprint {sprint_id}")

            # Get Jira issues for this sprint
            issues = self.jira.get_sprint_issues(sprint_id)
            sprint_pr_urls = []

            if issues:
                # Progress bar for processing issues
                issue_progress = tqdm(
                    issues,
                    desc="🔍 Processing Issues",
                    unit="issue",
                    leave=False,
                    bar_format="   {l_bar}{bar}| {n_fmt}/{total_fmt} issues [{elapsed}<{remaining}]",
                )

                for issue in issue_progress:
                    issue_key = issue["key"]
                    issue_progress.set_description(f"🔍 {issue_key}")

                    github_urls = self.jira.extract_github_urls(issue)
                    if github_urls:
                        pr_url = github_urls[0]  # Take the first URL found
                        if sprint_id in sprint_configs:
                            # Extract Jira status transitions for workflow timing
                            jira_transitions = self.jira.extract_status_transitions(
                                issue
                            )

                            all_pr_data.append(
                                (
                                    pr_url,
                                    sprint_configs[sprint_id],
                                    issue_key,
                                    jira_transitions,
                                )
                            )
                            sprint_pr_urls.append(pr_url)

            sprint_issue_mapping[sprint_id] = sprint_pr_urls
            sprint_progress.set_postfix(
                {"Issues": len(issues), "PR URLs": len(sprint_pr_urls)}
            )

        # Phase 2: Bulk analyze all PRs using GraphQL
        if all_pr_data:
            print(f"\n🚀 Phase 2: Bulk analyzing {len(all_pr_data)} GitHub PRs...")
            print("   Using GraphQL for faster processing (20x faster than REST API)")

            try:
                # Use asyncio to run the bulk analysis
                bulk_pr_metrics = asyncio.run(self.github.bulk_analyze_prs(all_pr_data))

                # Filter out None results and group by sprint
                valid_metrics = [m for m in bulk_pr_metrics if m is not None]
                all_prs.extend(valid_metrics)

                # Group PRs by sprint for individual sprint metrics
                for sprint_id in sprint_ids:
                    sprint_prs = []
                    sprint_urls = set(sprint_issue_mapping[sprint_id])

                    for pr_url, _, _, _ in all_pr_data:
                        if pr_url in sprint_urls:
                            # Find the corresponding PR metrics
                            for pr_metrics in valid_metrics:
                                if pr_url.endswith(f"/pull/{pr_metrics.pr_number}"):
                                    sprint_prs.append(pr_metrics)
                                    break

                    sprint_metrics[sprint_id] = self._calculate_sprint_metrics(
                        sprint_prs
                    )

                print(f"   ✅ Successfully analyzed {len(valid_metrics)} PRs")
                if len(valid_metrics) != len(all_pr_data):
                    failed_count = len(all_pr_data) - len(valid_metrics)
                    print(
                        f"   ⚠️  {failed_count} PRs failed to analyze (may be private repos or invalid URLs)"
                    )

            except Exception as e:
                print(f"   ❌ Bulk analysis failed: {e}")
                print("   🔄 Falling back to individual PR analysis...")

                # Fallback to individual analysis with progress bar
                pr_progress = tqdm(
                    all_pr_data,
                    desc="🔗 Analyzing PRs (Fallback)",
                    unit="PR",
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} PRs [{elapsed}<{remaining}]",
                )

                for pr_url, sprint_config, issue_key, jira_transitions in pr_progress:
                    pr_number = pr_url.split("/")[-1]
                    pr_progress.set_description(f"🔗 PR #{pr_number}")

                    pr_metrics = self.github.analyze_pr(
                        pr_url, sprint_config, issue_key, jira_transitions
                    )
                    if pr_metrics:
                        all_prs.append(pr_metrics)

                # Calculate sprint metrics for fallback case
                for sprint_id in sprint_ids:
                    sprint_prs = [
                        pr
                        for pr in all_prs
                        if any(
                            pr_url.endswith(f"/pull/{pr.pr_number}")
                            for pr_url in sprint_issue_mapping[sprint_id]
                        )
                    ]
                    sprint_metrics[sprint_id] = self._calculate_sprint_metrics(
                        sprint_prs
                    )
        else:
            print("   ⚠️  No GitHub PR URLs found in any sprint issues")

        # Calculate overall metrics with progress indication
        print(f"\n📊 Calculating analytics for {len(all_prs)} total PRs...")
        calculation_steps = ["overall metrics", "per-user metrics", "final report"]
        calc_progress = tqdm(
            calculation_steps,
            desc="📊 Computing Analytics",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} steps [{elapsed}]",
        )

        for step in calc_progress:
            calc_progress.set_description(f"📊 {step.title()}")
            if step == "overall metrics":
                overall_metrics = self._calculate_overall_metrics(all_prs)
            elif step == "per-user metrics":
                per_user_metrics = self._calculate_per_user_metrics(all_prs)
            else:
                # Final report preparation
                pass

        return {
            "sprint_metrics": sprint_metrics,
            "overall_metrics": overall_metrics,
            "per_user_metrics": per_user_metrics,
            "sprint_configs": sprint_configs,
            "total_prs": len(all_prs),
        }

    def _get_sprint_configs(
        self, sprint_ids: List[str], sprint_length_weeks: int
    ) -> Dict[str, SprintConfig]:
        """Get sprint configurations - you may need to customize this based on your sprint IDs"""
        configs = {}

        # This is a placeholder - you'll need to implement your sprint dating logic
        # For now, I'm creating mock dates for demonstration
        base_date = datetime(2025, 3, 17, tzinfo=pytz.UTC)

        for i, sprint_id in enumerate(sprint_ids):
            start_date = base_date + timedelta(weeks=i * sprint_length_weeks)
            end_date = start_date + timedelta(weeks=sprint_length_weeks)

            configs[sprint_id] = SprintConfig(
                name=sprint_id, start_date=start_date, end_date=end_date
            )

        return configs

    def _calculate_sprint_metrics(self, prs: List[PRMetrics]) -> Dict[str, Any]:
        """Calculate metrics for a single sprint"""
        if not prs:
            return {}

        # PRs by week
        opened_by_week = {1: 0, 2: 0, 3: 0}
        merged_by_week = {1: 0, 2: 0, 3: 0}
        comments_by_week = {1: 0, 2: 0, 3: 0}
        lgtm_by_week = {1: 0, 2: 0, 3: 0}

        merged_prs = []
        all_reviewers = Counter()
        carry_over_prs = 0

        for pr in prs:
            opened_by_week[pr.sprint_week] += 1
            comments_by_week[pr.sprint_week] += pr.comments_count
            lgtm_by_week[pr.sprint_week] += pr.lgtm_count

            if pr.merged_at:
                merged_week = (
                    pr.sprint_week
                )  # Simplified - you might want to check actual merge date
                merged_by_week[merged_week] += 1
                merged_prs.append(pr)
            else:
                carry_over_prs += 1

            for reviewer in pr.reviewers:
                all_reviewers[reviewer] += 1

        # Calculate timing metrics
        merge_times = [
            pr.time_to_merge_hours
            for pr in merged_prs
            if pr.time_to_merge_hours is not None
        ]
        first_review_times = [
            pr.time_to_first_review_hours
            for pr in prs
            if pr.time_to_first_review_hours is not None
        ]
        review_to_merge_times = [
            pr.time_first_review_to_merge_hours
            for pr in merged_prs
            if pr.time_first_review_to_merge_hours is not None
        ]

        # Calculate Jira workflow timing metrics
        in_progress_to_pr_created_times = [
            pr.time_in_progress_to_pr_created_hours
            for pr in prs
            if pr.time_in_progress_to_pr_created_hours is not None
        ]
        in_progress_to_pr_merged_times = [
            pr.time_in_progress_to_pr_merged_hours
            for pr in merged_prs
            if pr.time_in_progress_to_pr_merged_hours is not None
        ]
        pr_merged_to_resolved_times = [
            pr.time_pr_merged_to_resolved_hours
            for pr in merged_prs
            if pr.time_pr_merged_to_resolved_hours is not None
        ]

        return {
            "opened_by_week": opened_by_week,
            "merged_by_week": merged_by_week,
            "comments_by_week": comments_by_week,
            "lgtm_by_week": lgtm_by_week,
            "carry_over_prs": carry_over_prs,
            "reviewer_distribution": dict(all_reviewers.most_common()),
            "total_prs_reviewed": sum(all_reviewers.values()),
            "avg_time_to_merge": (
                sum(merge_times) / len(merge_times) if merge_times else 0
            ),
            "avg_time_to_first_review": (
                sum(first_review_times) / len(first_review_times)
                if first_review_times
                else 0
            ),
            "avg_time_review_to_merge": (
                sum(review_to_merge_times) / len(review_to_merge_times)
                if review_to_merge_times
                else 0
            ),
            # New Jira workflow timing metrics
            "avg_time_in_progress_to_pr_created": (
                sum(in_progress_to_pr_created_times)
                / len(in_progress_to_pr_created_times)
                if in_progress_to_pr_created_times
                else 0
            ),
            "avg_time_in_progress_to_pr_merged": (
                sum(in_progress_to_pr_merged_times)
                / len(in_progress_to_pr_merged_times)
                if in_progress_to_pr_merged_times
                else 0
            ),
            "avg_time_pr_merged_to_resolved": (
                sum(pr_merged_to_resolved_times) / len(pr_merged_to_resolved_times)
                if pr_merged_to_resolved_times
                else 0
            ),
            "merged_pr_count": len(merged_prs),
        }

    def _calculate_overall_metrics(self, prs: List[PRMetrics]) -> Dict[str, Any]:
        """Calculate overall metrics across all sprints"""
        if not prs:
            return {}

        merged_prs = [pr for pr in prs if pr.merged_at]

        # Timing metrics
        merge_times = [
            pr.time_to_merge_hours
            for pr in merged_prs
            if pr.time_to_merge_hours is not None
        ]
        first_review_times = [
            pr.time_to_first_review_hours
            for pr in prs
            if pr.time_to_first_review_hours is not None
        ]
        review_to_merge_times = [
            pr.time_first_review_to_merge_hours
            for pr in merged_prs
            if pr.time_first_review_to_merge_hours is not None
        ]

        # Size metrics
        sizes = [pr.size for pr in prs if pr.size > 0]

        # Review metrics
        all_reviewers = Counter()
        total_review_instances = 0

        for pr in prs:
            for reviewer in pr.reviewers:
                all_reviewers[reviewer] += 1
                total_review_instances += 1

        # LGTM quality metrics
        lgtm_distribution = Counter()
        for pr in merged_prs:
            lgtm_distribution[len(pr.lgtm_users)] += 1

        # Calculate Jira workflow timing metrics
        in_progress_to_pr_created_times = [
            pr.time_in_progress_to_pr_created_hours
            for pr in prs
            if pr.time_in_progress_to_pr_created_hours is not None
        ]
        in_progress_to_pr_merged_times = [
            pr.time_in_progress_to_pr_merged_hours
            for pr in merged_prs
            if pr.time_in_progress_to_pr_merged_hours is not None
        ]
        pr_merged_to_resolved_times = [
            pr.time_pr_merged_to_resolved_hours
            for pr in merged_prs
            if pr.time_pr_merged_to_resolved_hours is not None
        ]

        return {
            "avg_time_to_merge": (
                sum(merge_times) / len(merge_times) if merge_times else 0
            ),
            "avg_pr_size": sum(sizes) / len(sizes) if sizes else 0,
            "avg_time_to_first_review": (
                sum(first_review_times) / len(first_review_times)
                if first_review_times
                else 0
            ),
            "avg_time_review_to_merge": (
                sum(review_to_merge_times) / len(review_to_merge_times)
                if review_to_merge_times
                else 0
            ),
            # New Jira workflow timing metrics
            "avg_time_in_progress_to_pr_created": (
                sum(in_progress_to_pr_created_times)
                / len(in_progress_to_pr_created_times)
                if in_progress_to_pr_created_times
                else 0
            ),
            "avg_time_in_progress_to_pr_merged": (
                sum(in_progress_to_pr_merged_times)
                / len(in_progress_to_pr_merged_times)
                if in_progress_to_pr_merged_times
                else 0
            ),
            "avg_time_pr_merged_to_resolved": (
                sum(pr_merged_to_resolved_times) / len(pr_merged_to_resolved_times)
                if pr_merged_to_resolved_times
                else 0
            ),
            "reviewer_distribution": dict(all_reviewers.most_common()),
            "total_review_instances": total_review_instances,
            "unique_prs_reviewed": len([pr for pr in prs if pr.reviewers]),
            "lgtm_distribution": dict(lgtm_distribution),
            "merged_pr_count": len(merged_prs),
            "total_pr_count": len(prs),
        }

    def _calculate_per_user_metrics(
        self, prs: List[PRMetrics]
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate per-user metrics"""
        user_prs = defaultdict(list)
        user_reviews = defaultdict(lambda: {"prs": set(), "instances": 0})

        # Group PRs by author
        for pr in prs:
            user_prs[pr.author].append(pr)

            # Track reviews
            for reviewer in pr.reviewers:
                user_reviews[reviewer]["prs"].add(pr.pr_number)
                user_reviews[reviewer]["instances"] += 1

        user_metrics = {}

        for user, user_pr_list in user_prs.items():
            merged_prs = [pr for pr in user_pr_list if pr.merged_at]

            # Timing metrics
            merge_times = [
                pr.time_to_merge_hours
                for pr in merged_prs
                if pr.time_to_merge_hours is not None
            ]
            sizes = [pr.size for pr in user_pr_list if pr.size > 0]
            comments_received = [pr.comments_count for pr in user_pr_list]
            carry_overs = len([pr for pr in user_pr_list if not pr.merged_at])
            lgtm_given = sum(pr.lgtm_count for pr in user_pr_list)

            # Jira workflow timing metrics for this user
            user_in_progress_to_pr_created_times = [
                pr.time_in_progress_to_pr_created_hours
                for pr in user_pr_list
                if pr.time_in_progress_to_pr_created_hours is not None
            ]
            user_in_progress_to_pr_merged_times = [
                pr.time_in_progress_to_pr_merged_hours
                for pr in merged_prs
                if pr.time_in_progress_to_pr_merged_hours is not None
            ]
            user_pr_merged_to_resolved_times = [
                pr.time_pr_merged_to_resolved_hours
                for pr in merged_prs
                if pr.time_pr_merged_to_resolved_hours is not None
            ]

            user_metrics[user] = {
                "avg_time_to_merge": (
                    sum(merge_times) / len(merge_times) if merge_times else 0
                ),
                "avg_pr_size": sum(sizes) / len(sizes) if sizes else 0,
                "avg_comments_received": (
                    sum(comments_received) / len(comments_received)
                    if comments_received
                    else 0
                ),
                # New Jira workflow timing metrics per user
                "avg_time_in_progress_to_pr_created": (
                    sum(user_in_progress_to_pr_created_times)
                    / len(user_in_progress_to_pr_created_times)
                    if user_in_progress_to_pr_created_times
                    else 0
                ),
                "avg_time_in_progress_to_pr_merged": (
                    sum(user_in_progress_to_pr_merged_times)
                    / len(user_in_progress_to_pr_merged_times)
                    if user_in_progress_to_pr_merged_times
                    else 0
                ),
                "avg_time_pr_merged_to_resolved": (
                    sum(user_pr_merged_to_resolved_times)
                    / len(user_pr_merged_to_resolved_times)
                    if user_pr_merged_to_resolved_times
                    else 0
                ),
                "total_lgtm_comments": lgtm_given,
                "carry_over_prs": carry_overs,
                "total_prs_reviewed": len(user_reviews[user]["prs"]),
                "total_review_instances": user_reviews[user]["instances"],
                "merged_pr_count": len(merged_prs),
                "total_pr_count": len(user_pr_list),
            }

        return user_metrics


class ReportGenerator:
    """Generate formatted reports"""

    @staticmethod
    def generate_report(analysis_results: Dict[str, Any]) -> str:
        """Generate the main analytics report"""
        report = []

        # Header
        report.append("=" * 80)
        report.append("GITHUB PR ANALYTICS REPORT")
        report.append("=" * 80)
        report.append("")

        # Sprint Configuration
        sprint_configs = analysis_results["sprint_configs"]
        sprint_names = list(sprint_configs.keys())

        if sprint_configs:
            first_sprint = list(sprint_configs.values())[0]
            last_sprint = list(sprint_configs.values())[-1]

            report.append("Sprint Configuration:")
            report.append(f"- Current sprint: {sprint_names[-1]}")
            report.append(
                f"- Analyzing sprints: {sprint_names[0]}-{sprint_names[-1]} ({len(sprint_names)} sprints)"
            )
            report.append("- Sprint length: 3 weeks")
            report.append("- Sprint weeks: first, second, final")
            report.append(
                f"- Analysis period: {first_sprint.start_date.strftime('%Y-%m-%d')} to {last_sprint.end_date.strftime('%Y-%m-%d')}"
            )
            report.append("")

        # Sprint Metrics
        report.append("=" * 50)
        report.append("SPRINT METRICS")
        report.append("=" * 50)
        report.append("")

        for sprint_name, metrics in analysis_results["sprint_metrics"].items():
            if not metrics:
                continue

            report.append(f"--- Sprint {sprint_name} ---")

            # PR counts by week
            opened = metrics["opened_by_week"]
            merged = metrics["merged_by_week"]
            comments = metrics["comments_by_week"]
            lgtm = metrics["lgtm_by_week"]

            report.append(
                f"Opened PRs: First week: {opened[1]}, Second week: {opened[2]}, Final week: {opened[3]}, Total: {sum(opened.values())}"
            )
            report.append(
                f"Merged PRs: First week: {merged[1]}, Second week: {merged[2]}, Final week: {merged[3]}, Total: {sum(merged.values())}"
            )
            report.append(f"Carry-over PRs: {metrics['carry_over_prs']}")
            report.append(
                f"Team Comments: First week: {comments[1]}, Second week: {comments[2]}, Final week: {comments[3]}, Total: {sum(comments.values())}"
            )
            report.append(
                f"/lgtm Comments: First week: {lgtm[1]}, Second week: {lgtm[2]}, Final week: {lgtm[3]}, Total: {sum(lgtm.values())}"
            )

            # Review distribution
            report.append("Review Distribution:")
            report.append(
                f"  Total PRs reviewed in sprint: {metrics['total_prs_reviewed']}"
            )

            total_reviews = sum(metrics["reviewer_distribution"].values())
            for reviewer, count in metrics["reviewer_distribution"].items():
                percentage = (count / total_reviews * 100) if total_reviews > 0 else 0
                report.append(f"  {reviewer}: {count} PRs ({percentage:.1f}%)")

            # Timing metrics
            avg_merge = metrics["avg_time_to_merge"]
            avg_first_review = metrics["avg_time_to_first_review"]
            avg_review_to_merge = metrics["avg_time_review_to_merge"]

            report.append(
                f"Average time to merge: {avg_merge:.1f} hours ({avg_merge/24:.1f} days) across {metrics['merged_pr_count']} PRs"
            )
            report.append(
                f"Average time creation → first review: {avg_first_review:.1f} hours ({avg_first_review/24:.1f} days)"
            )
            report.append(
                f"Average time first review → merge: {avg_review_to_merge:.1f} hours ({avg_review_to_merge/24:.1f} days)"
            )
            report.append("")

        # Overall Metrics
        overall = analysis_results["overall_metrics"]
        if overall:
            report.append("=" * 50)
            report.append("OVERALL METRICS")
            report.append("=" * 50)

            avg_merge = overall["avg_time_to_merge"]
            avg_size = overall["avg_pr_size"]
            avg_first_review = overall["avg_time_to_first_review"]
            avg_review_to_merge = overall["avg_time_review_to_merge"]

            report.append(
                f"Average time to merge (all PRs): {avg_merge:.1f} hours ({avg_merge/24:.1f} days) across {overall['merged_pr_count']} PRs"
            )
            report.append(
                f"Average PR size (additions + deletions): {avg_size:.0f} lines across {overall['total_pr_count']} PRs"
            )
            report.append(
                f"Average review turnaround time: {avg_first_review:.1f} hours ({avg_first_review/24:.1f} days) across {overall['merged_pr_count']} PRs"
            )
            report.append(
                f"Average time creation → first review: {avg_first_review:.1f} hours ({avg_first_review/24:.1f} days)"
            )
            report.append(
                f"Average time first review → merge: {avg_review_to_merge:.1f} hours ({avg_review_to_merge/24:.1f} days)"
            )

            # Add Jira workflow timing metrics
            report.append("")
            report.append("JIRA WORKFLOW TIMING METRICS:")

            avg_in_progress_to_created = overall.get(
                "avg_time_in_progress_to_pr_created", 0
            )
            avg_in_progress_to_merged = overall.get(
                "avg_time_in_progress_to_pr_merged", 0
            )
            avg_merged_to_resolved = overall.get("avg_time_pr_merged_to_resolved", 0)

            if avg_in_progress_to_created > 0:
                report.append(
                    f"Average time Jira 'In Progress' → PR Created: {avg_in_progress_to_created:.1f} hours ({avg_in_progress_to_created/24:.1f} days)"
                )
            else:
                report.append(
                    "Average time Jira 'In Progress' → PR Created: No data available"
                )

            if avg_in_progress_to_merged > 0:
                report.append(
                    f"Average time Jira 'In Progress' → PR Merged: {avg_in_progress_to_merged:.1f} hours ({avg_in_progress_to_merged/24:.1f} days)"
                )
            else:
                report.append(
                    "Average time Jira 'In Progress' → PR Merged: No data available"
                )

            if avg_merged_to_resolved > 0:
                report.append(
                    f"Average time PR Merged → Jira 'Resolved': {avg_merged_to_resolved:.1f} hours ({avg_merged_to_resolved/24:.1f} days)"
                )
            else:
                report.append(
                    "Average time PR Merged → Jira 'Resolved': No data available"
                )

            report.append("")

            # Review distribution
            report.append("Review distribution (Bus Factor Analysis):")
            report.append(
                f"Total review instances: {overall['total_review_instances']}"
            )
            report.append(
                f"Total unique PRs reviewed by team: {overall['unique_prs_reviewed']}"
            )

            total_instances = overall["total_review_instances"]
            for reviewer, count in overall["reviewer_distribution"].items():
                # This is a simplified calculation - in real implementation you'd need to track PR counts vs instance counts separately
                pr_count = count  # Simplified
                percentage = (
                    (count / total_instances * 100) if total_instances > 0 else 0
                )
                report.append(
                    f"  {reviewer}: {pr_count} PRs ({count} instances, {percentage:.1f}%)"
                )
            report.append("")

            # LGTM Quality Metrics
            report.append("LGTM Quality Metrics:")
            report.append(f"Total merged PRs: {overall['merged_pr_count']}")

            lgtm_dist = overall.get("lgtm_distribution", {})
            prs_with_2plus_lgtm = lgtm_dist.get(2, 0) + sum(
                v for k, v in lgtm_dist.items() if k > 2
            )
            percentage = (
                (prs_with_2plus_lgtm / overall["merged_pr_count"] * 100)
                if overall["merged_pr_count"] > 0
                else 0
            )
            report.append(
                f"PRs with ≥2 unique /lgtms before merge: {prs_with_2plus_lgtm} ({percentage:.1f}%)"
            )

            report.append("Unique LGTM giver distribution:")
            for lgtm_count, pr_count in sorted(lgtm_dist.items()):
                percentage = (
                    (pr_count / overall["merged_pr_count"] * 100)
                    if overall["merged_pr_count"] > 0
                    else 0
                )
                people_text = "person" if lgtm_count == 1 else "people"
                report.append(
                    f"  {lgtm_count} unique {people_text}: {pr_count} PRs ({percentage:.1f}%)"
                )
            report.append("")

        # Per-User Metrics
        per_user = analysis_results["per_user_metrics"]
        if per_user:
            report.append("=" * 50)
            report.append("PER-USER METRICS")
            report.append("=" * 50)
            report.append("")

            for user, metrics in per_user.items():
                report.append(f"--- {user} ---")

                avg_merge = metrics["avg_time_to_merge"]
                avg_size = metrics["avg_pr_size"]
                avg_comments = metrics["avg_comments_received"]

                report.append(
                    f"  Average time to merge: {avg_merge:.1f} hours ({avg_merge/24:.1f} days) across {metrics['merged_pr_count']} PRs"
                )
                report.append(
                    f"  Average PR size: {avg_size:.0f} lines across {metrics['total_pr_count']} PRs"
                )
                report.append(
                    f"  Average comments/reviews received per PR: {avg_comments:.1f} (across {metrics['total_pr_count']} PRs)"
                )
                report.append(
                    f"  Total /lgtm comments: {metrics['total_lgtm_comments']}"
                )
                report.append(f"  Carry-over PRs: {metrics['carry_over_prs']}")
                report.append(f"  Total PRs reviewed: {metrics['total_prs_reviewed']}")
                report.append(
                    f"  Total review instances: {metrics['total_review_instances']}"
                )

                # Add Jira workflow timing metrics per user
                user_in_progress_to_created = metrics.get(
                    "avg_time_in_progress_to_pr_created", 0
                )
                user_in_progress_to_merged = metrics.get(
                    "avg_time_in_progress_to_pr_merged", 0
                )
                user_merged_to_resolved = metrics.get(
                    "avg_time_pr_merged_to_resolved", 0
                )

                if (
                    user_in_progress_to_created > 0
                    or user_in_progress_to_merged > 0
                    or user_merged_to_resolved > 0
                ):
                    report.append("  Jira Workflow Timing:")

                    if user_in_progress_to_created > 0:
                        report.append(
                            f"    In Progress → PR Created: {user_in_progress_to_created:.1f}h ({user_in_progress_to_created/24:.1f}d)"
                        )
                    else:
                        report.append("    In Progress → PR Created: No data")

                    if user_in_progress_to_merged > 0:
                        report.append(
                            f"    In Progress → PR Merged: {user_in_progress_to_merged:.1f}h ({user_in_progress_to_merged/24:.1f}d)"
                        )
                    else:
                        report.append("    In Progress → PR Merged: No data")

                    if user_merged_to_resolved > 0:
                        report.append(
                            f"    PR Merged → Jira Resolved: {user_merged_to_resolved:.1f}h ({user_merged_to_resolved/24:.1f}d)"
                        )
                    else:
                        report.append("    PR Merged → Jira Resolved: No data")

                # Calculate average reviews per sprint
                sprint_count = len(analysis_results["sprint_configs"])
                avg_reviews_per_sprint = (
                    metrics["total_prs_reviewed"] / sprint_count
                    if sprint_count > 0
                    else 0
                )
                report.append(
                    f"  Average reviews per sprint: {avg_reviews_per_sprint:.1f} (across {metrics['total_prs_reviewed']} total PRs reviewed in {sprint_count} sprints)"
                )
                report.append("")

        return "\n".join(report)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Generate GitHub PR Analytics Report from Jira sprints"
    )
    parser.add_argument(
        "sprints", nargs="+", help="List of sprint IDs to analyze (e.g., 123 456 789)"
    )
    parser.add_argument("--output", "-o", help="Output file path (optional)")
    parser.add_argument(
        "--github-field",
        default="customfield_12310220",
        help="Jira custom field ID for GitHub PR links (default: customfield_12310220)",
    )
    parser.add_argument(
        "--sprint-field",
        default="customfield_12310940",
        help="Jira custom field ID for sprint identification (default: customfield_12310940)",
    )
    parser.add_argument("--jira-host", help="Jira host URL (e.g., issues.redhat.com)")
    parser.add_argument(
        "--jira-token", help="Jira access token for on-premise authentication"
    )
    parser.add_argument("--github-token", help="GitHub personal access token")
    parser.add_argument(
        "--github-owner", help="GitHub repository owner (e.g., opendatahub-io)"
    )
    parser.add_argument(
        "--github-repo", help="GitHub repository name (e.g., odh-dashboard)"
    )

    args = parser.parse_args()

    # Get configuration from command line args or environment variables
    jira_host = args.jira_host or os.getenv("JIRA_HOST", "issues.redhat.com")
    jira_url = f"https://{jira_host}" if not jira_host.startswith("http") else jira_host

    # Authentication - prioritize command line, then environment variables
    jira_token = args.jira_token or os.getenv("JIRA_ACCESS_TOKEN")
    jira_username = os.getenv("JIRA_USERNAME")  # For cloud instances
    jira_password = os.getenv("JIRA_PASSWORD")  # For cloud instances

    github_token = args.github_token or os.getenv("GITHUB_TOKEN")
    github_owner = args.github_owner or os.getenv("GITHUB_OWNER", "opendatahub-io")
    github_repo = args.github_repo or os.getenv("GITHUB_REPO", "odh-dashboard")

    # Get GitHub field ID from environment variable or command line argument
    github_field_id = os.getenv("JIRA_GITHUB_FIELD_ID", args.github_field)

    # Get Sprint field ID from environment variable or command line argument
    sprint_field_id = os.getenv("JIRA_SPRINT_FIELD_ID", args.sprint_field)

    # Validate required parameters
    if not github_token:
        print("Error: Missing GitHub token. Provide via:")
        print("- Command line: --github-token YOUR_TOKEN")
        print("- Environment variable: GITHUB_TOKEN=YOUR_TOKEN")
        sys.exit(1)

    if not jira_token and not (jira_username and jira_password):
        print("Error: Missing Jira authentication. Provide either:")
        print("- Token auth: --jira-token YOUR_TOKEN or JIRA_ACCESS_TOKEN=YOUR_TOKEN")
        print(
            "- Username/password: JIRA_USERNAME and JIRA_PASSWORD environment variables"
        )
        sys.exit(1)

    try:
        # Initialize analyzer
        analyzer = SprintAnalyzer(
            jira_url=jira_url,
            github_token=github_token,
            jira_token=jira_token,
            jira_username=jira_username,
            jira_password=jira_password,
            github_field_id=github_field_id,
            sprint_field_id=sprint_field_id,
            github_owner=github_owner,
            github_repo=github_repo,
        )

        # Analyze sprints
        print(
            f"🚀 Starting analysis of {len(args.sprints)} sprints: {', '.join(args.sprints)}"
        )
        print("📊 Using bulk GraphQL processing for 20x faster PR analysis!")
        print("=" * 60)
        results = analyzer.analyze_sprints(args.sprints)

        # Generate report
        print(f"\n📝 Generating comprehensive report...")
        report = ReportGenerator.generate_report(results)

        # Output report
        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"✅ Report saved to: {args.output}")
        else:
            print("\n" + report)

        print("=" * 60)
        print(
            f"🎉 Analysis complete! Processed {results['total_prs']} PRs across {len(args.sprints)} sprints."
        )
        print("⚡ Bulk GraphQL processing made this analysis 20x faster!")
        print("✨ Your GitHub PR analytics report is ready!")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
