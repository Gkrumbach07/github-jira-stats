# GitHub PR Analytics Report Generator

This Python script analyzes GitHub Pull Requests associated with Jira issues from specified sprints and generates comprehensive analytics reports.

## Features

- **Sprint-level metrics**: PR counts by week, merge statistics, review distribution
- **Overall metrics**: Cross-sprint analytics, timing metrics, review patterns
- **Per-user metrics**: Individual developer performance and review contributions
- **GitHub integration**: Automatic PR analysis including size, reviews, and timing
- **Jira integration**: Extracts GitHub PR links from Jira issues in specified sprints
- **Jira workflow timing**: Tracks timing from Jira status changes to PR events
- **Progress tracking**: Beautiful progress bars show real-time analysis status
- **Bulk processing**: GraphQL-powered bulk PR analysis (20x faster than individual requests)

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

# Run the script directly (using sprint IDs)
python sprint_analytics.py "123" "124" "125"
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
| `--output` / `-o` | - | - | Output file path |

## How It Works

1. **Jira Integration**: For each sprint ID, the script:
   - Uses JQL: `Sprint = "sprint_id"`
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

- **Sprint Configuration**: Overview of analyzed sprints and time periods
- **Sprint Metrics**: Week-by-week breakdown for each sprint
- **Overall Metrics**: Cross-sprint analytics and trends, including GitHub PR timing and **Jira workflow timing**
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

## License

This script is provided as-is for internal use. Modify as needed for your organization's requirements.
