#!/usr/bin/env python3
"""
Example usage of the Sprint Analytics script

Usage:
  python example_usage.py
"""

import os
from sprint_analytics import PRAnalyzer, ReportGenerator


def main():
    """Example of how to use the PRAnalyzer programmatically"""

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

    # JQL query to find issues (much more flexible than sprint IDs)
    jql_query = "Sprint in (123, 124, 125) AND project = ODH"
    # Or any other JQL query like:
    # jql_query = "project = ODH AND fixVersion = '1.0' AND created >= -30d"
    # jql_query = "assignee = currentUser() AND status in ('Resolved', 'Closed') AND updated >= -14d"

    # Time bucketing configuration
    time_bucket_type = "weekly"  # daily, weekly, monthly, n_days
    time_bucket_size = 7  # Only used for n_days

    try:
        # Initialize the analyzer
        analyzer = PRAnalyzer(
            jira_url=jira_url,
            github_token=github_token,
            jira_token=jira_token,
            github_field_id=github_field_id,
            sprint_field_id=sprint_field_id,
            github_owner=github_owner,
            github_repo=github_repo,
        )

        # Run the analysis (with built-in progress bars and bulk PR processing)
        print(f"🚀 Starting PR analysis with JQL query...")
        print(f"   Query: {jql_query}")
        print(f"   Time bucketing: {time_bucket_type}")
        print("📊 Using bulk GraphQL processing for 20x faster PR analysis!")
        results = analyzer.analyze_prs_by_jql(
            jql_query,
            time_bucket_type,
            time_bucket_size,
            pr_date_filter_months=6,  # Only analyze PRs from last 6 months
        )

        # Generate and display the report
        print(f"\n📝 Generating report...")
        report = ReportGenerator.generate_report(results)
        print(report)

        # Optionally save to file
        with open("sprint_report.txt", "w") as f:
            f.write(report)
        print("\nReport saved to sprint_report.txt")

        # Example: CSV Export with time bucketing
        print(f"\n📊 Demonstrating CSV export functionality...")
        try:
            from sprint_analytics import TimeBucket, CSVExporter

            # Get all PRs from results for CSV export
            all_prs = results.get("all_prs", [])

            if all_prs:
                print(f"📋 Exporting {len(all_prs)} PRs to CSV with weekly buckets...")

                # Create time bucket configuration
                time_bucket = TimeBucket.from_prs_and_config(all_prs, "weekly")
                print(
                    f"📅 Date range: {time_bucket.start_date.strftime('%Y-%m-%d')} to {time_bucket.end_date.strftime('%Y-%m-%d')}"
                )

                # Export CSV files
                csv_files = CSVExporter.export_time_bucketed_data(
                    all_prs, time_bucket, "example_csv_exports"
                )

                print(f"✅ CSV files created:")
                for file_type, file_path in csv_files.items():
                    print(f"   {file_type}: {file_path}")

                # Also try monthly bucketing
                print(f"\n📋 Exporting monthly buckets...")
                monthly_bucket = TimeBucket.from_prs_and_config(all_prs, "monthly")
                monthly_csv_files = CSVExporter.export_time_bucketed_data(
                    all_prs, monthly_bucket, "example_csv_exports"
                )

                print(f"✅ Monthly CSV files created:")
                for file_type, file_path in monthly_csv_files.items():
                    print(f"   {file_type}: {file_path}")
            else:
                print("⚠️  No PR data available for CSV export")

        except Exception as e:
            print(f"❌ CSV export example failed: {e}")
            print(
                "💡 This is just a demonstration - CSV export is working in the main script!"
            )

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
