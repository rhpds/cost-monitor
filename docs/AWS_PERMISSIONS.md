# AWS Permissions Setup for Cost Monitor

The Cost Monitor requires specific AWS permissions to access Cost Explorer and Organizations APIs for full functionality. You can choose between basic permissions (Cost Explorer only) or full permissions (Cost Explorer + Organizations for account name resolution).

## Required Permissions

### 1. Cost Explorer Permissions (Required)
- `ce:GetCostAndUsage` - Retrieve cost data
- `ce:GetDimensionValues` - Get available dimensions
- `ce:GetReservationCoverage` - Reservation data
- `ce:GetReservationPurchaseRecommendation` - Reservation recommendations
- `ce:GetReservationUtilization` - Reservation utilization
- `ce:ListCostCategoryDefinitions` - Cost categories
- `ce:GetCostCategories` - Cost category values

### 2. Organizations Permissions (Required for Account Names)
- `organizations:DescribeAccount` - Get account details and names
- `organizations:DescribeOrganization` - Identify management account
- `organizations:ListAccounts` - List organization accounts
- `organizations:ListRoots` - List organization roots
- `organizations:ListOrganizationalUnitsForParent` - List OUs
- `organizations:ListChildren` - List child accounts/OUs

## Setup Instructions

### Option 1: Using the AWS Credentials Script (Recommended)

1. Run the AWS credentials setup script:
   ```bash
   ./scripts/create-aws-credentials.sh
   ```

2. The script will automatically:
   - Create a new IAM user with comprehensive permissions
   - Generate access keys
   - Apply full Cost Explorer + Organizations permissions

### Option 2: Manual Policy Application

If you have existing AWS credentials and just want to add Organizations permissions:

1. Use the policy file in `assets/aws-iam-policy.json`:
   ```bash
   aws iam create-policy \
       --policy-name CostMonitorPolicy \
       --policy-document file://assets/aws-iam-policy.json
   ```

2. Attach the policy to your IAM user:
   ```bash
   aws iam attach-user-policy \
       --user-name YOUR_USERNAME \
       --policy-arn arn:aws:iam::YOUR_ACCOUNT:policy/CostMonitorPolicy
   ```

   Or attach to an IAM role:
   ```bash
   aws iam attach-role-policy \
       --role-name YOUR_ROLE_NAME \
       --policy-arn arn:aws:iam::YOUR_ACCOUNT:policy/CostMonitorPolicy
   ```

## Verification

### Test Permissions
```bash
# Test Organizations access
aws organizations describe-organization

# Test Cost Explorer access
aws ce get-cost-and-usage \
    --time-period Start=2025-12-01,End=2025-12-08 \
    --granularity DAILY \
    --metrics BlendedCost
```

### Check Applied Policies
```bash
# For IAM user
aws iam list-attached-user-policies --user-name YOUR_USERNAME

# For IAM role
aws iam list-attached-role-policies --role-name YOUR_ROLE_NAME
```

## Error Messages and Solutions

### "AWS Organizations access denied"
**Error**: `❌ AWS Organizations access denied for account XXXXX. Required permissions: organizations:DescribeAccount, organizations:DescribeOrganization`

**Solution**: Run `./scripts/create-aws-credentials.sh` to set up full permissions, or manually apply the Organizations policy from `assets/aws-iam-policy.json`.

### "Account not found in organization"
**Info**: Some accounts may not be part of your AWS Organization. This is expected and the system will display the account ID instead of a friendly name.

### "Throttling" or Rate Limit Errors
**Info**: AWS Cost Explorer has rate limits. The system includes retry logic with exponential backoff.

## Account Name Display Features

When properly configured, the Cost Monitor will:

1. **Show Friendly Names**: Display account names instead of just IDs
   - Format: `Account Name (123456789012)`

2. **Identify Management Account**: Mark the organization's management account
   - Format: `Management Account Name (123456789012) (Management Account)`

3. **Handle External Accounts**: Accounts outside your organization show as account ID only

## Security Considerations

- **Least Privilege**: The policy provides minimum required permissions
- **Read-Only**: All permissions are read-only; no modify/delete capabilities
- **Organization Scope**: Organizations permissions apply to your entire AWS Organization
- **Regional**: Cost Explorer is only available in `us-east-1` region

## Troubleshooting

### Common Issues

1. **Wrong Region**: Cost Explorer requires `us-east-1` region
2. **Billing Access**: Ensure the user has billing/cost access enabled
3. **Organization Permissions**: User must be in the management account or have cross-account Organizations access
4. **Cache Issues**: Clear cache after permission changes: `./service.sh clear-cache aws`

### Debug Mode

Enable debug logging in `config/config.yaml`:
```yaml
logging:
  level: "DEBUG"
```

This will show detailed API request/response information for troubleshooting.
