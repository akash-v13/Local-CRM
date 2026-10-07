"""Shopify: order lookup (a built-in enrichment step) and issuing compensation
(refunds, store credit, discount codes) on the business's own store.

client.py  the Admin GraphQL API (pure HTTP, no database)
orders.py  turning a Shopify order into the fields cases, rules and templates use
"""
