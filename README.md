# GitHub PR Analytics Report Generator

This Python script analyzes GitHub Pull Requests associated with Jira issues using flexible JQL queries and generates comprehensive analytics reports with configurable time bucketing.

## Features

- **Flexible JQL queries**: Use any JQL query to filter Jira issues (not limited to sprints)
- **Time-bucketed metrics**: Analyze data by daily, weekly, monthly, or custom time periods
- **Overall metrics**: Cross-period analytics, timing metrics, review patterns
- **Per-user metrics**: Individual developer performance and review contributions
- **GitHub integration**: Automatic PR analysis including size, reviews, and timing
- **Jira integration**: Extracts GitHub PR links from any Jira issues matching your query
- **Jira workflow timing**: Tracks timing from Jira status changes to PR events
- **Progress tracking**: Beautiful progress bars show real-time analysis status
- **Bulk processing**: GraphQL-powered bulk PR analysis (20x faster than individual requests)
- **Time-bucketed CSV export**: Export data by daily, weekly, monthly, or custom time periods

## Setup

### 1. Install Dependencies

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Recommended: Install dependencies only (for standalone script)
uv pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file and configure your credentials:

```bash
cp env.example .env
```

Then edit the `.env` file with the following variables:

```bash
# Jira Configuration (On-premise with Token Authentication)
JIRA_HOST=issues.redhat.com
JIRA_ACCESS_TOKEN=your-jira-access-token

# GitHub Configuration
GITHUB_TOKEN=ghp_your_github_personal_access_token
GITHUB_OWNER=opendatahub-io
GITHUB_REPO=odh-dashboard

# Jira Custom Field Configuration
JIRA_GITHUB_FIELD_ID=customfield_12310220  # GitHub PR links field
```

#### Getting API Credentials

**Jira Access Token (On-premise):**
1. Contact your Jira administrator for an access token
2. Or use personal access tokens if enabled in your Jira instance
3. Set as `JIRA_ACCESS_TOKEN` environment variable

**Jira API Token (Cloud):**
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Use your email as username and the token as password

**GitHub Personal Access Token:**
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate a new token with `repo` permissions
3. Copy the token (starts with `ghp_`)


## Usage

### Basic Usage (using environment variables)

```bash
# Set up environment variables first
cp env.example .env
# Edit .env with your credentials

# Run the script with JQL queries (much more flexible!)
python sprint_analytics.py "Sprint in (123, 124, 125)"

# Or use any JQL query you want
python sprint_analytics.py "project = MYPROJ AND fixVersion = '2.0'"
python sprint_analytics.py "assignee = currentUser() AND updated >= -30d"
python sprint_analytics.py "project = MYPROJ AND created >= '2024-01-01'"
```

### CSV Export (Time-Bucketed Analytics)

Export your data to CSV files with flexible time bucketing for advanced analysis and visualization:

```bash
# Enable CSV export with weekly buckets (default)
python sprint_analytics.py "Sprint in (123, 124, 125)" --csv-export

# Export with different time buckets
python sprint_analytics.py "project = MYPROJ AND fixVersion = '2.0'" --csv-export --time-bucket daily
python sprint_analytics.py "assignee = currentUser() AND updated >= -30d" --csv-export --time-bucket monthly
python sprint_analytics.py "project = MYPROJ AND created >= '2024-01-01'" --csv-export --time-bucket n_days --bucket-size 10

# Custom output directory  
python sprint_analytics.py "Sprint in (123, 124, 125)" --csv-export --csv-output-dir my_data
```

**Time Bucket Options:**
- `daily`: One row per day
- `weekly`: One row per week (Monday to Sunday)
- `monthly`: One row per calendar month
- `n_days`: Custom time periods (specify days with `--bucket-size`)

**Output Files:**
- `overall_metrics_{bucket_type}.csv`: Overall team metrics over time
- `user_{username}_{bucket_type}.csv`: Individual user metrics over time
- `summary_metrics.csv`: **NEW!** Overall metrics in first row, per-user metrics in subsequent rows (not time-bucketed)

**CSV Columns Include:**
- Time period information
- PR counts (total, merged, merge rate)
- Size metrics (avg PR size)
- Timing metrics (time to merge, time to review)
- **Jira workflow metrics** (In Progress → PR Created, PR Merged → Resolved)
- Review metrics (comments, LGTMs, reviewer counts)

**Example Time-Bucketed CSV Data:**
```csv
time_period,total_prs,merged_prs,avg_time_to_merge_hours,avg_in_progress_to_pr_created_hours
2024-01,23,21,48.2,12.5
2024-02,19,18,36.8,8.3
2024-03,27,25,52.1,15.2
```

**Example Summary CSV Data:**
```csv
user,total_prs,merged_prs,merge_rate,avg_pr_size,avg_time_to_merge_hours,avg_time_to_first_review_hours
OVERALL,67,58,86.5,245.3,18.5,4.2
john.doe,23,20,87.0,234.1,19.2,4.5
jane.smith,18,15,83.3,267.8,17.3,3.9
alice.dev,12,11,91.7,189.2,16.8,4.8
bob.engineer,14,12,85.7,298.4,20.1,3.7
```

### Why Use uv?

**uv** is a fast Python package installer and resolver that's 10-100x faster than pip:
- ⚡ **Speed**: Installs dependencies in seconds, not minutes
- 🔒 **Reliability**: Better dependency resolution and lock files
- 🛠️ **Modern**: Built for modern Python packaging standards
- 🔄 **Compatibility**: Works with existing pip requirements.txt files
- 📦 **Efficiency**: Better caching and parallel downloads

```bash
# Quick comparison
time pip install -r requirements.txt      # ~30-60 seconds
time uv pip install -r requirements.txt   # ~3-5 seconds
```

### Command Line Options

| Option | Environment Variable | Default | Description |
|--------|---------------------|---------|-------------|
| `--jira-host` | `JIRA_HOST` | `issues.redhat.com` | Jira host URL |
| `--jira-token` | `JIRA_ACCESS_TOKEN` | - | Jira access token (on-premise) |
| `--github-token` | `GITHUB_TOKEN` | - | GitHub personal access token |
| `--github-owner` | `GITHUB_OWNER` | `opendatahub-io` | GitHub repository owner |
| `--github-repo` | `GITHUB_REPO` | `odh-dashboard` | GitHub repository name |
| `--github-field` | `JIRA_GITHUB_FIELD_ID` | `customfield_12310220` | Jira custom field for PR links |
| `--sprint-field` | `JIRA_SPRINT_FIELD_ID` | `customfield_12310940` | Jira custom field for sprint identification |
| `--output` / `-o` | - | - | Output file path |
| `--csv-export` | `CSV_EXPORT` | `false` | Enable CSV export |
| `--time-bucket` | `TIME_BUCKET_TYPE` | `weekly` | Time bucketing: daily, weekly, monthly, n_days |
| `--bucket-size` | `TIME_BUCKET_SIZE` | `7` | Days per bucket (for n_days) |
| `--csv-output-dir` | `CSV_OUTPUT_DIR` | `csv_exports` | CSV output directory |
| `--pr-date-filter-months` | `PR_DATE_FILTER_MONTHS` | `6` | Only include PRs created within this many months ago (0 = disable) |

## How It Works

1. **Jira Integration**: Using your JQL query, the script:
   - Executes your custom JQL query (e.g., `"Sprint in (123, 124)" or "project = MYPROJ AND fixVersion = '2.0'"`)
   - Handles pagination automatically for large result sets
   - Extracts GitHub PR URLs with priority order:
     1. **Primary**: Custom field `customfield_12310220` (GitHub PR field)
     2. **Fallback**: Issue descriptions, comments, and other custom fields
   - Uses regex patterns to find GitHub PR links

2. **Bulk GitHub Analysis**: For all PRs found:
   - **Phase 1**: Collects all GitHub PR URLs from all Jira issues
   - **Phase 2**: Groups PRs by repository for optimal GraphQL batching  
   - **Bulk Fetch**: Uses GitHub GraphQL API to fetch 20 PRs per request
   - Analyzes timing metrics (creation, first review, merge)
   - Counts reviews, comments, and LGTM mentions
   - Calculates PR size (additions + deletions) 
   - Determines which sprint week the PR was created in
   - **Fallback**: Automatically switches to individual REST API if bulk fails

3. **Analytics Calculation**: 
   - Groups data by sprint and week
   - Calculates review distribution and timing statistics
   - Generates per-user performance metrics
   - Computes overall cross-sprint trends
   - **Jira Workflow Analysis**: Tracks timing between Jira status changes and GitHub PR events

4. **Report Generation**: Creates a comprehensive formatted report similar to the sample output

### Jira Workflow Timing Metrics

The script tracks three critical workflow timing metrics that provide insights into development cycle efficiency:

**📊 New Timing Metrics:**
- **In Progress → PR Created**: Time from when a Jira issue moves to "In Progress" status until a GitHub PR is created
- **In Progress → PR Merged**: Total time from "In Progress" status until the PR is successfully merged  
- **PR Merged → Resolved**: Time from PR merge until the Jira issue is marked as "Resolved"/"Done"/"Closed"

These metrics help identify bottlenecks in your development workflow and measure the efficiency of your team's development process from Jira ticket creation through to completion.

## Sample Output Structure

The script generates a report with the following sections:

- **Time Bucket Configuration**: Overview of analyzed time periods and date ranges
- **Time Bucket Metrics**: Period-by-period breakdown (daily/weekly/monthly based on your choice)
- **Overall Metrics**: Cross-period analytics and trends, including GitHub PR timing and **Jira workflow timing**
- **Per-User Metrics**: Individual developer performance, including personal workflow timing metrics

**Sample Jira Workflow Timing Output:**
```
JIRA WORKFLOW TIMING METRICS:
Average time Jira 'In Progress' → PR Created: 18.5 hours (0.8 days)
Average time Jira 'In Progress' → PR Merged: 72.3 hours (3.0 days)
Average time PR Merged → Jira 'Resolved': 4.2 hours (0.2 days)
```

**Sample Per-User Jira Workflow Timing:**
```
--- john.doe ---
  Jira Workflow Timing:
    In Progress → PR Created: 12.3h (0.5d)
    In Progress → PR Merged: 48.7h (2.0d)
    PR Merged → Jira Resolved: 2.1h (0.1d)
```

## Customization

### Sprint Date Calculation

Modify the `_get_sprint_configs` method to match your sprint scheduling:

```python
def _get_sprint_configs(self, sprint_ids: List[str], sprint_length_weeks: int) -> Dict[str, SprintConfig]:
    # Implement your sprint date calculation logic here
    # Example: parse sprint IDs and calculate dates based on your schedule
```

### GitHub URL Extraction

The script looks for GitHub PR URLs in:
- **Primary source**: Custom field `customfield_12310220` (GitHub PR field)
- **Fallback sources**: 
  - Jira issue descriptions
  - Issue comments  
  - Other custom fields

The script prioritizes the dedicated GitHub PR custom field (12310220) for better accuracy and performance.

### Metrics Calculation

The `PRMetrics` dataclass and calculation methods can be extended to include additional metrics like:
- Code review quality scores
- PR approval workflows
- Custom timing measurements

## Requirements

- Python 3.8.1+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip for dependency management
- Jira API access with appropriate permissions  
- GitHub API access with repo permissions
- Network access to both Jira and GitHub instances

## Project Structure

The project uses modern Python packaging with `pyproject.toml` and supports both traditional pip and modern uv workflows:

```
jira-github-stats/
├── sprint_analytics.py      # Main script
├── example_usage.py         # Programmatic usage example
├── pyproject.toml          # Modern Python packaging config
├── requirements.txt        # Legacy pip compatibility  
├── env.example            # Environment configuration template
├── .gitignore            # Git ignore rules
└── README.md            # Documentation
```

## Troubleshooting

### Old PRs Showing in Recent Analysis

**Problem**: Your JQL query targets recent Jira issues (e.g., "last 16 weeks") but you're seeing PR analytics going back months or years.

**Cause**: Recent Jira issues can link to old GitHub PRs. Time bucketing is based on GitHub PR creation dates, not Jira issue dates.

**Solution**: Use PR date filtering:

```bash
# Only analyze PRs from last 3 months (good for recent work)
python sprint_analytics.py "project = MYPROJ AND updated >= -16w" --pr-date-filter-months 3

# Only analyze PRs from last 1 month (very recent only)  
python sprint_analytics.py "Sprint in (123, 124)" --pr-date-filter-months 1

# Disable filtering to see all PRs (original behavior)
python sprint_analytics.py "project = MYPROJ AND updated >= -16w" --pr-date-filter-months 0
```

The script will show you exactly what's being filtered:
```
🔍 PR date range before filtering: 2024-01-15 to 2024-08-30
   Cutoff date: 2024-05-30 12:34:56
🗓️  Filtered out 23 PRs older than 3 months
   Remaining PRs: 45
   New PR date range: 2024-05-30 to 2024-08-30
```

## Other Troubleshooting

**Common Issues:**

1. **Python Version Conflicts**: If you get dependency resolution errors with uv, ensure you're using Python 3.8.1 or newer:
   ```bash
   python --version  # Should show 3.8.1 or higher
   uv sync           # Try again after confirming Python version
   ```

2. **Authentication Errors**: Verify API credentials and permissions
3. **Sprint Not Found**: Check sprint name spelling and Jira access
4. **GitHub Rate Limits**: The script includes basic error handling; consider adding delays for large datasets
5. **No PRs Found**: Verify that Jira issues contain GitHub PR links in searchable fields

**Debug Mode:**

Add print statements or modify logging to see detailed processing information:

```python
print(f"Found {len(github_urls)} GitHub URLs in issue {issue_key}")
```

## 📊 Progress Tracking

The script includes beautiful progress bars that show:
- **Sprint Progress**: Overall progress through all sprints
- **Issue Processing**: Progress extracting GitHub URLs from Jira issues  
- **PR Analysis**: Progress analyzing each GitHub PR
- **Analytics Computation**: Final calculation steps

Example output:
```
🚀 Starting analysis of 3 sprints: 123, 124, 125
============================================================
🔍 Phase 1: Collecting GitHub PR URLs from Jira issues...
📋 Fetching Issues: 100%|██████████| 3/3 sprints [00:15<00:00]

🚀 Phase 2: Bulk analyzing 67 GitHub PRs...
   Using GraphQL for faster processing (20x faster than REST API)
   ✅ Successfully analyzed 65 PRs
   ⚠️  2 PRs failed to analyze (may be private repos or invalid URLs)

📊 Computing Analytics: 100%|██████████| 3/3 steps [00:02<00:00]
🎉 Analysis complete! Processed 65 PRs across 3 sprints.
```

This makes it easy to estimate completion time and see which step is currently running.

## Performance Notes

**🚀 Bulk Processing (Default):**
- Uses GitHub GraphQL API to fetch up to 20 PRs per request
- **20x faster** than individual REST API calls
- For large datasets (100+ PRs), expect processing time of 30 seconds - 2 minutes
- Processes all repositories in parallel batches
- Automatic fallback to individual analysis if bulk processing fails

**⚡ Performance Comparison:**
- **Individual REST API**: ~2-5 seconds per PR → 100 PRs = 3-8 minutes
- **Bulk GraphQL API**: ~20 PRs per batch → 100 PRs = 15-30 seconds

**📊 API Rate Limits:**
- GitHub GraphQL API: 5000 points/hour (much more efficient than REST)
- Each bulk query (~20 PRs) uses ~100 points vs 2000+ for individual REST calls
- Progress bars provide real-time feedback and time estimates
- Consider caching results for repeated analysis of the same sprints

**📊 CSV Export Performance:**
- Time-bucketed CSV export processes all PRs in memory
- Large datasets (1000+ PRs) may take additional 10-30 seconds for CSV generation
- CSV files are optimized with pandas for fast loading in analysis tools
- Separate files per user prevent memory issues with large teams

## License

This script is provided as-is for internal use. Modify as needed for your organization's requirements.
