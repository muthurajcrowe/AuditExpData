github test project

## Submit invoice + store extraction in Cosmos DB

Run `submit_invoice_to_foundry.py` with the following environment variables:

- `DOCUMENTINTELLIGENCE_ENDPOINT`
- `DOCUMENTINTELLIGENCE_API_KEY` (or use AAD auth via `az login`)
- `COSMOS_ENDPOINT`
- `COSMOS_KEY`
- `COSMOS_DATABASE`
- `COSMOS_CONTAINER`

The script extracts invoice fields from Azure AI Document Intelligence (`prebuilt-invoice`) and writes the extraction payload into the configured Azure Cosmos DB container.
