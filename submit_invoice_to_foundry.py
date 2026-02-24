"""Submit an invoice document to Azure AI Foundry Document Intelligence (prebuilt-invoice model).

Usage:
    export DOCUMENTINTELLIGENCE_ENDPOINT="https://<your-resource>.cognitiveservices.azure.com/"
    export DOCUMENTINTELLIGENCE_API_KEY="<your-key>"
    python submit_invoice_to_foundry.py /path/to/invoice.pdf

To store extracted data in Azure Cosmos DB, also set:
    export COSMOS_ENDPOINT="https://<your-account>.documents.azure.com:443/"
    export COSMOS_KEY="<your-cosmos-key>"
    export COSMOS_DATABASE="<database-name>"
    export COSMOS_CONTAINER="<container-name>"

Optional (AAD auth instead of API key):
    unset DOCUMENTINTELLIGENCE_API_KEY
    az login
    python submit_invoice_to_foundry.py /path/to/invoice.pdf
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.cosmos import CosmosClient, exceptions
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential


def build_client(endpoint: str, api_key: str | None) -> DocumentIntelligenceClient:
    """Create a DocumentIntelligenceClient using API key or Entra ID auth."""
    if api_key:
        return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(api_key))
    return DocumentIntelligenceClient(endpoint=endpoint, credential=DefaultAzureCredential())


def extract_invoice_fields(result: Any) -> dict[str, Any]:
    """Return a concise dict of commonly used invoice fields."""
    output: dict[str, Any] = {"documents": []}

    for doc in result.documents:
        fields = doc.fields or {}
        parsed = {
            "vendorName": fields.get("VendorName").value_string if fields.get("VendorName") else None,
            "invoiceId": fields.get("InvoiceId").value_string if fields.get("InvoiceId") else None,
            "invoiceDate": str(fields.get("InvoiceDate").value_date) if fields.get("InvoiceDate") else None,
            "customerName": fields.get("CustomerName").value_string if fields.get("CustomerName") else None,
            "subTotal": fields.get("SubTotal").value_currency.amount if fields.get("SubTotal") and fields.get("SubTotal").value_currency else None,
            "totalTax": fields.get("TotalTax").value_currency.amount if fields.get("TotalTax") and fields.get("TotalTax").value_currency else None,
            "invoiceTotal": fields.get("InvoiceTotal").value_currency.amount if fields.get("InvoiceTotal") and fields.get("InvoiceTotal").value_currency else None,
            "currency": fields.get("InvoiceTotal").value_currency.currency_code if fields.get("InvoiceTotal") and fields.get("InvoiceTotal").value_currency else None,
            "confidence": doc.confidence,
        }
        output["documents"].append(parsed)

    return output


def analyze_invoice(file_path: Path) -> dict[str, Any]:
    endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
    api_key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY")

    if not endpoint:
        raise ValueError("Set DOCUMENTINTELLIGENCE_ENDPOINT in your environment.")

    client = build_client(endpoint=endpoint, api_key=api_key)

    with file_path.open("rb") as f:
        poller = client.begin_analyze_document(
            model_id="prebuilt-invoice",
            body=f,
            content_type="application/octet-stream",
        )

    result = poller.result()
    return extract_invoice_fields(result)


def store_in_cosmos(invoice_data: dict[str, Any], source_file: Path) -> str:
    """Persist extracted invoice data into Azure Cosmos DB and return created item id."""
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    key = os.environ.get("COSMOS_KEY")
    database = os.environ.get("COSMOS_DATABASE")
    container = os.environ.get("COSMOS_CONTAINER")

    missing = [
        env_name
        for env_name, env_value in {
            "COSMOS_ENDPOINT": endpoint,
            "COSMOS_KEY": key,
            "COSMOS_DATABASE": database,
            "COSMOS_CONTAINER": container,
        }.items()
        if not env_value
    ]
    if missing:
        raise ValueError(f"Missing required Cosmos DB configuration: {', '.join(missing)}")

    cosmos_client = CosmosClient(url=endpoint, credential=key)
    container_client = cosmos_client.get_database_client(database).get_container_client(container)

    first_doc = (invoice_data.get("documents") or [{}])[0]
    item = {
        "id": str(uuid4()),
        "invoiceId": first_doc.get("invoiceId") or str(uuid4()),
        "sourceFile": source_file.name,
        "processedAtUtc": datetime.now(timezone.utc).isoformat(),
        "extract": invoice_data,
    }

    try:
        container_client.create_item(body=item)
    except exceptions.CosmosHttpResponseError as exc:
        raise RuntimeError(f"Failed to write invoice extraction to Cosmos DB: {exc}") from exc

    return item["id"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit an invoice file to Azure Document Intelligence.")
    parser.add_argument("invoice_file", type=Path, help="Path to PDF/image invoice file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.invoice_file.exists():
        raise FileNotFoundError(f"Invoice file not found: {args.invoice_file}")

    invoice_data = analyze_invoice(args.invoice_file)
    cosmos_item_id = store_in_cosmos(invoice_data, args.invoice_file)
    print(json.dumps(invoice_data, indent=2, default=str))
    print(f"Saved extracted invoice data to Cosmos DB item id: {cosmos_item_id}")


if __name__ == "__main__":
    main()
