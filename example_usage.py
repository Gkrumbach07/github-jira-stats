#!/usr/bin/env python3
"""
Example usage of the Sprint Analytics script

Usage:
  python example_usage.py
"""

import os
from sprint_analytics import SprintAnalyzer, ReportGenerator


def main():
    """Example of how to use the SprintAnalyzer programmatically"""

    # Configuration (you can also use environment variables)
    jira_url = "https://issues.redhat.com"
    jira_token = "your-jira-access-token"  # For on-premise Jira
    github_token = "ghp_your_github_token"
    github_field_id = "customfield_12310220"  # Custom field ID for GitHub PRs
    sprint_field_id = (
        "customfield_12310940"  # Custom field ID for sprint identification
    )
    github_owner = "opendatahub-io"
    github_repo = "odh-dashboard"

    # Sprint IDs to analyze (usually numeric IDs, not names)
    sprint_ids = ["123", "124", "125", "126", "127"]

    try:
        # Initialize the analyzer
        analyzer = SprintAnalyzer(
            jira_url=jira_url,
            github_token=github_token,
            jira_token=jira_token,
            github_field_id=github_field_id,
            sprint_field_id=sprint_field_id,
            github_owner=github_owner,
            github_repo=github_repo,
        )

        # Run the analysis (with built-in progress bars and bulk PR processing)
        print(f"🚀 Starting analysis of {len(sprint_ids)} sprints...")
        print("📊 Using bulk GraphQL processing for 20x faster PR analysis!")
        results = analyzer.analyze_sprints(sprint_ids)

        # Generate and display the report
        print(f"\n📝 Generating report...")
        report = ReportGenerator.generate_report(results)
        print(report)

        # Optionally save to file
        with open("sprint_report.txt", "w") as f:
            f.write(report)
        print("\nReport saved to sprint_report.txt")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
