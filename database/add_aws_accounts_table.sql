-- Add AWS accounts table to existing database
-- This can be run against the existing PostgreSQL database

-- Create AWS account names table for persistent account resolution
CREATE TABLE IF NOT EXISTS aws_accounts (
    account_id VARCHAR(12) PRIMARY KEY,
    account_name VARCHAR(255) NOT NULL,
    is_management_account BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_aws_accounts_updated
ON aws_accounts(last_updated DESC);

CREATE INDEX IF NOT EXISTS idx_aws_accounts_status
ON aws_accounts(status, last_updated DESC);

-- Create function to automatically update the last_updated timestamp
CREATE OR REPLACE FUNCTION update_aws_account_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to automatically update timestamp on account name changes
DROP TRIGGER IF EXISTS trigger_update_aws_account_timestamp ON aws_accounts;
CREATE TRIGGER trigger_update_aws_account_timestamp
    BEFORE UPDATE ON aws_accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_aws_account_timestamp();

COMMENT ON TABLE aws_accounts IS 'Persistent storage for AWS account ID to name mappings';
COMMENT ON COLUMN aws_accounts.account_id IS 'AWS Account ID (12-digit string)';
COMMENT ON COLUMN aws_accounts.account_name IS 'Human-readable AWS account name from Organizations API';
COMMENT ON COLUMN aws_accounts.is_management_account IS 'Whether this is the AWS Organizations management account';
COMMENT ON COLUMN aws_accounts.status IS 'Account status: active, suspended, closed';