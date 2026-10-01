# Webflow development installation

The Webflow integration is a Data Client app with a server-side OAuth callback, an automatic published-content scan and a registered custom-code widget. It is not a browser extension or a Designer-only panel.

1. Host the included Voca service on an HTTPS domain and configure its AI key.
2. Register a Webflow Data Client app in your developer workspace. `app-config.json` is a worksheet for the registration screen, not an uploadable marketplace manifest.
3. Configure the OAuth callback as `https://YOUR-AGENT-DOMAIN/oauth/webflow/callback`. Put `WEBFLOW_CLIENT_ID` and `WEBFLOW_CLIENT_SECRET` on the service.
4. Set the scopes shown in the worksheet. Custom-code API calls require an OAuth app token, not a site token.
5. In Voca, add the published website URL, select Webflow, and enter the site’s 24-character ID. Choose Connect Webflow and authorize the intended site.
6. Voca validates access and domain ownership, queues the first published HTML scan and queues widget installation.
7. In Webflow, publish your site when ready. Custom-code changes take effect on publication. Voca does not publish all staged changes automatically.
8. Inspect the widget and imported content report.

The public sitemap and rendered same-origin pages include accessible CMS detail pages. Unpublished/private CMS fields are not imported. Client-only content, PDFs and image text require other importers. Sites with robots.txt disallowing scans will need their own approved source importer.

Content refreshes every six hours. Optionally register a `site_publish` webhook with the destination `https://YOUR-AGENT-DOMAIN/webhooks/webflow` through the OAuth app. The server validates Webflow’s signature and timestamp before queueing a scan. Dashboard-created unsigned webhook requests are rejected.

The widget is registered with its SHA-256 integrity hash at `/widget/v1/widget.js`. Keep that asset immutable after the first real registration. Changes require a new versioned URL, a new registered version, updated references and any required marketplace review. Existing scripts are preserved when adding or removing Voca.

Disconnect/remove the guide from Voca before uninstalling the app so it can remove its applied script while OAuth access still exists, then publish the site to complete removal. If access was already revoked, remove the applied script in Webflow and publish manually. Deleting a Voca tenant disables server answers immediately even if the script remains on the site.

No Webflow app registration or marketplace review has been completed here. Real OAuth/custom-code behavior must be tested on your developer app and site. The registration worksheet requests site and script access; the content crawler reads only publicly available HTML. Additional API importers would need their own scopes.

Official guides:
- https://developers.webflow.com/data/reference/oauth-app
- https://developers.webflow.com/data/docs/working-with-custom-code
- https://developers.webflow.com/data/docs/working-with-webhooks
