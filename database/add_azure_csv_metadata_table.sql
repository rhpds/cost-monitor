-- Add Azure CSV metadata table to existing database
-- This can be run against the existing PostgreSQL database

-- Create Azure CSV metadata table for ETag-based incremental billing-export downloads
-- Tracks each Azure Cost Management CSV blob so downloads/parsing can be skipped when unchanged
CREATE TABLE IF NOT EXISTS azure_csv_metadata (
    blob_name TEXT PRIMARY KEY,
    etag TEXT,
    file_size_bytes BIGINT,
    last_downloaded TIMESTAMP WITH TIME ZONE,
    last_parsed TIMESTAMP WITH TIME ZONE,
    parse_status VARCHAR(20) DEFAULT 'pending',
    record_count INTEGER,
    date_range_start DATE,
    date_range_end DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_azure_csv_metadata_status
ON azure_csv_metadata(parse_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_azure_csv_metadata_downloaded
ON azure_csv_metadata(last_downloaded DESC);

COMMENT ON TABLE azure_csv_metadata IS 'Tracks Azure billing-export CSV blobs (ETag, parse status) for incremental downloads';
COMMENT ON COLUMN azure_csv_metadata.blob_name IS 'Full blob path of the Azure Cost Management CSV export';
COMMENT ON COLUMN azure_csv_metadata.etag IS 'Blob ETag used for conditional (If-None-Match) downloads';
COMMENT ON COLUMN azure_csv_metadata.parse_status IS 'Parse status: pending, completed, failed';
COMMENT ON COLUMN azure_csv_metadata.record_count IS 'Number of cost records parsed from this CSV';
