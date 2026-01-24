# Dashboard Features Guide

The interactive web dashboard provides comprehensive visualization and analysis of multi-cloud costs through an intuitive interface built with Plotly and Dash.

## Accessing the Dashboard

### OpenShift Deployment

```bash
# Get the dashboard URL
oc get route cost-monitor-dashboard-route -o jsonpath='{.spec.host}'

# Access via browser
https://your-dashboard-route.apps.cluster.example.com
```

### Local Development

```bash
# Start the dashboard
python -m src.main dashboard

# Access via browser
http://localhost:8050
```

### Docker Deployment

```bash
# With Docker Compose
docker-compose up -d

# Access via browser
http://localhost:8050
```

## Dashboard Overview

The dashboard consists of several key sections:

1. **Summary Cards** - Quick overview of total costs and trends
2. **Cost Trends Chart** - Time-series visualization of spending patterns
3. **Provider Breakdown** - Pie chart showing cost distribution by cloud provider
4. **Service Analysis** - Detailed breakdown by cloud services
5. **Account/Project View** - Multi-account cost analysis
6. **Controls Panel** - Filtering and configuration options

## Interactive Controls

### Date Range Selection

**Predefined Ranges:**
- Last 7 days
- Last 30 days
- Last 90 days
- Month to date
- Year to date
- Custom range

**Custom Date Picker:**
- Click on the date range selector
- Choose start and end dates
- Data automatically refreshes

```python
# Programmatic date range (for custom integrations)
from datetime import datetime, timedelta

# Last 30 days
end_date = datetime.now()
start_date = end_date - timedelta(days=30)
```

### Provider Filtering

**Available Filters:**
- **All Providers** - Combined view across AWS, Azure, and GCP
- **AWS Only** - Amazon Web Services costs
- **Azure Only** - Microsoft Azure costs
- **GCP Only** - Google Cloud Platform costs

**Multi-Provider Selection:**
- Use checkboxes to select multiple providers
- Comparison charts automatically update
- Totals recalculate based on selection

### Granularity Options

**Time Granularity:**
- **Daily** - Day-by-day cost breakdown (default for ranges ≤ 90 days)
- **Monthly** - Month-by-month aggregation (default for ranges > 90 days)
- **Weekly** - Week-by-week summary (available for custom ranges)

### Auto-Refresh Settings

**Refresh Options:**
- **Manual** - Update data manually via refresh button
- **5 minutes** - Automatic refresh every 5 minutes
- **15 minutes** - Automatic refresh every 15 minutes
- **30 minutes** - Automatic refresh every 30 minutes
- **1 hour** - Automatic refresh every hour

## Cost Visualization Features

### Summary Cards

**Total Cost Card:**
- Current period total spending
- Percentage change from previous period
- Color-coded trend indicators (green/yellow/red)

**Daily Average Card:**
- Average daily spend for selected period
- Comparison with historical averages
- Trend arrow indicators

**Top Service Card:**
- Highest spending cloud service
- Cost amount and percentage of total
- Service provider identification

**Cost Trend Card:**
- Overall spending direction
- Percentage change indicators
- Visual trend line

### Cost Trends Chart

**Features:**
- Interactive time-series visualization
- Hover tooltips with detailed information
- Zoom and pan capabilities
- Multi-provider comparison lines
- Logarithmic scale option for large variance

**Customization:**
- Toggle between providers
- Switch between cost types (blended, unblended, amortized)
- Change chart type (line, bar, area)

**Example Interactions:**
- **Hover** - View exact costs for specific dates
- **Click Legend** - Toggle provider visibility
- **Zoom** - Select time range for detailed analysis
- **Double-click** - Reset zoom to full range

### Provider Breakdown (Pie Chart)

**Information Displayed:**
- Percentage of total costs by provider
- Absolute cost amounts
- Number of services per provider
- Interactive legend

**Interactions:**
- **Click Slice** - Filter to specific provider
- **Hover** - View detailed provider information
- **Legend Click** - Toggle provider visibility

### Service Analysis

**Service-Level Breakdown:**
- Top spending services across all providers
- Service cost trends over time
- Provider-specific service grouping
- Search and filter capabilities

**Table Features:**
- **Sortable Columns** - Click headers to sort by cost, provider, or service
- **Search Filter** - Find specific services quickly
- **Pagination** - Navigate through large service lists
- **Export Options** - Download data as CSV

**Columns:**
- **Service Name** - Cloud service identifier
- **Provider** - AWS, Azure, or GCP
- **Current Cost** - Spending for selected period
- **Previous Cost** - Spending for previous period
- **Change %** - Percentage change between periods
- **Trend** - Visual trend indicator

### Account/Project View

**Multi-Account Analysis:**
- AWS account breakdown
- Azure subscription analysis
- GCP project-level costs
- Cross-account comparisons

**Features:**
- **Account Grouping** - Organize by business units or environments
- **Cost Allocation** - View shared cost distributions
- **Trend Analysis** - Account-level spending patterns
- **Budget Tracking** - Compare against allocated budgets

### Geographic Distribution (Premium Feature)

**Regional Cost Analysis:**
- Costs by AWS regions
- Azure geographic regions
- GCP zones and regions
- Interactive world map

## Performance Features

### Smart Caching

**Cache Levels:**
- **Browser Cache** - Client-side figure caching for fast interactions
- **Application Cache** - Server-side data caching with Redis
- **Provider Cache** - Cloud API response caching

**Cache Indicators:**
- Fresh data indicator (green)
- Cached data age display
- Manual refresh option to bypass cache

### Lazy Loading

**Efficient Data Loading:**
- Initial page loads essential data only
- Additional charts load as needed
- Background data prefetching for smooth interactions
- Progressive enhancement for large datasets

### Responsive Design

**Mobile Optimization:**
- Responsive layouts for tablets and phones
- Touch-friendly controls
- Collapsible sidebar for small screens
- Optimized chart rendering for mobile

**Desktop Features:**
- Multi-monitor support
- Keyboard navigation
- Context menus
- Advanced filtering panels

## Advanced Features

### Custom Dashboards

**Dashboard Customization:**
- Rearrange chart order
- Show/hide specific visualizations
- Save custom layouts
- Export dashboard configurations

### Alerting Integration

**Visual Alerts:**
- Threshold exceedance notifications
- Cost spike warnings
- Budget limit indicators
- Service anomaly highlights

**Alert Configuration:**
- Set custom thresholds from dashboard
- Configure notification preferences
- Historical alert timeline

### Data Export

**Export Options:**
- **CSV Export** - Raw cost data for analysis
- **PDF Reports** - Formatted cost reports
- **Chart Images** - PNG/SVG chart exports
- **API Integration** - Programmatic data access

```bash
# Export current dashboard data
curl "http://localhost:8000/api/v1/costs/summary?format=csv" > costs.csv
```

### Comparison Tools

**Period Comparison:**
- Month-over-month analysis
- Year-over-year comparisons
- Custom period selection
- Variance analysis

**Provider Comparison:**
- Side-by-side cost comparisons
- Service mapping across providers
- Efficiency metrics
- Migration cost analysis

## Customization Options

### Themes

**Available Themes:**
- **Light Theme** - Default bright interface
- **Dark Theme** - Dark mode for low-light environments
- **High Contrast** - Accessibility-focused theme
- **Corporate** - Branded theme with company colors

### Chart Preferences

**Visualization Options:**
- Color palettes for providers
- Chart type preferences (line, bar, area)
- Default time ranges
- Currency display formats

### Layout Preferences

**Dashboard Layout:**
- Grid vs. stacked layouts
- Chart size preferences
- Sidebar position
- Information density

## Keyboard Shortcuts

**Navigation:**
- `Ctrl+R` - Refresh data
- `Tab` - Navigate between controls
- `Space` - Toggle selected items
- `Esc` - Clear selections

**Charts:**
- `+/-` - Zoom in/out on charts
- `Home` - Reset chart zoom
- `Arrow Keys` - Navigate data points

## Troubleshooting Dashboard Issues

### Common Problems

**Dashboard Not Loading:**
1. Check API service is running (`/api/health/ready`)
2. Verify network connectivity
3. Check browser console for JavaScript errors
4. Clear browser cache and cookies

**Charts Not Displaying:**
1. Verify data is available for selected date range
2. Check cloud provider authentication
3. Review browser console for errors
4. Try refreshing with cache bypass (`Ctrl+F5`)

**Slow Performance:**
1. Reduce date range for initial testing
2. Check network connection speed
3. Monitor browser memory usage
4. Consider using daily granularity for large ranges

**Authentication Issues:**
1. Verify OAuth proxy configuration (OpenShift)
2. Check session timeout settings
3. Try logging out and back in
4. Contact administrator for access permissions

### Debug Mode

Enable debug mode for troubleshooting:

```python
# Start dashboard in debug mode
python -m src.main dashboard --debug

# Or set environment variable
export DEBUG=true
python -m src.main dashboard
```

**Debug Features:**
- Detailed error messages
- Performance timing information
- Cache hit/miss indicators
- API request logging

For more troubleshooting information, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).