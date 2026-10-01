# Shopify development installation

This package contains a standalone Shopify app configuration and a theme app embed, backed by the shared Voca service.

1. Deploy the included service to your HTTPS domain. Configure an OpenAI API key in its dashboard or environment.
2. Create an app in the Shopify Dev Dashboard for your development store. Set `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` on the server.
3. Edit `shopify.app.toml`: fill `client_id`, `application_url`, and the exact OAuth callback URL. Request `read_products,read_content`. Keep the default `embedded=false`; this implementation uses standalone app authorization.
4. Install Shopify CLI from its official source and link this project to the registered app. Use its development/deploy workflow to register the `extensions/voca-widget` theme extension. Do not invent extension IDs; the CLI/platform generates them.
5. In Voca add your store using the **primary live storefront HTTPS domain**. Select Shopify. Enter the store’s `your-store.myshopify.com` hostname and choose Connect Shopify. Authorize content access. A first scan queues automatically.
6. In the store’s theme editor, open App embeds, enable Voca, and enter the HTTPS service origin and website ID shown in Voca. Save the theme. These are public widget values, not credentials.
7. Verify the widget on the storefront and check the imported content report.

The app receives product and collection update/deletion webhooks through the configured subscriptions. Pages and policies reconcile on the six-hour schedule. Uninstall disables the guide and removes platform access tokens; the mandatory shop-redaction webhook removes the tenant’s stored knowledge. The agent stores no customer records or visitor transcripts.

Crawl limits, robots restrictions and provider errors appear in job reports. Shopify products must have an online-store URL and ACTIVE status to be imported. Product price ranges are cached at sync time; the linked product page is authoritative. No live inventory quantity or authenticated order lookup is provided.

The operator dashboard uses a service administrator key. This development version does not offer merchant billing, self-service multi-merchant accounts or a marketplace-ready merchant dashboard. App Store distribution requires further product work, review and testing. The provided placeholder app configuration cannot deploy until it is linked to a real developer app.

Official guides:
- https://shopify.dev/docs/apps/build/online-store/theme-app-extensions
- https://shopify.dev/docs/apps/build/authentication-authorization/authenticate-standalone-apps
