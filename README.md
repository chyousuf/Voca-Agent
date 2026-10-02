# Voca Website AI Agent

Voca is a self-hosted website knowledge guide for WordPress, Shopify and Webflow. It imports public website content into a separate index for each connected site. Visitors can ask questions by voice or text and receive answers with links to relevant pages.

## Project status

The WordPress plugin has been installed and checked on a local WordPress site. The Shopify and Webflow integrations are development implementations; they still need platform developer apps and end-to-end testing on test stores/sites. AI answers require an OpenAI or Gemini API key. The repository does not include installation credentials or a production deployment.

## Run locally

Use Python 3.10 or newer. From the project directory:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python setup.py
python backend/run.py
```

`setup.py` creates a local `.env` with new administrator and encryption keys. Keep `.env`, the `data/` directory and backups private. Open `http://127.0.0.1:8787/admin` and sign in with `VOCA_ADMIN_TOKEN` from your local `.env`.

For a public website, deploy the service on HTTPS and install its platform integration using the setup steps below. A local service address such as `127.0.0.1` only works on the computer running Voca.

## What the three integrations include

| Platform | Integration | Automatic content coverage | Updates |
|---|---|---|---|
| WordPress | Uploadable PHP plugin; settings screen; automatic widget | Published pages, posts, public post types, supported Elementor text fields, visible WooCommerce products and product attributes | Content changes queue a snapshot sync; daily reconciliation through WordPress cron |
| Shopify | Standalone app backend authorization + Shopify theme app embed | Published online-store products, price ranges, collections, pages, policies; published storefront HTML adds articles and FAQs | Product/collection webhooks; periodic full refresh every six hours |
| Webflow | Data Client app authorization + integrity-checked custom-code installation | Public rendered HTML from sitemap and same-origin links, including published CMS pages | Periodic refresh every six hours; optional signed `site_publish` webhook |

“Website content” means published content intended for visitors. Orders, customer accounts, form submissions, drafts and private pages are not imported. WordPress password-protected posts and hidden WooCommerce products are excluded. Crawler imports respect robots.txt and noindex. PDFs, image OCR, video transcription, login-gated data, JavaScript-only content and arbitrary private CMS fields need dedicated importers. WordPress shortcodes are stripped rather than executed. Elementor text is read from a defined list of text-bearing fields; dynamically generated content may need another importer.

In the dashboard, owners can see each indexed page’s last successful indexing time, identify stale content, retry a full sync, and exclude or restore a page. Exclusions persist across syncs. The WordPress plugin fetches the exclusion list before each batch and pauses sync if it cannot verify that list.

The default crawl cap is 300 pages, reported in the dashboard when reached. Increase `VOCA_MAX_PAGES` for a larger published site. Partial crawls retain existing content rather than silently pruning an incomplete snapshot. Shopify API records have their own authoritative reconciliation so unpublished or removed API content is retired even if the HTML crawl is partial.

## Install the shared service

All three integrations depend on this service; a Shopify theme block alone cannot index a store or answer questions.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python setup.py
python backend/run.py
```

`setup.py` creates `.env` with new random administrator and encryption keys. It preserves existing configuration. Keep `VOCA_ENCRYPTION_KEY` with your encrypted database backups; losing it makes stored platform/API credentials unreadable.

For public sites, host this service on an HTTPS domain and set `VOCA_BASE_URL` to that origin. Use the supplied Dockerfile/compose file or a Python host behind an HTTPS reverse proxy. The nginx example is in `docs/nginx.conf.example`. Keep the service’s listener private behind your proxy. Use a persistent `data/` volume, backups and platform credentials supplied as secrets. Python’s bundled HTTP server, SQLite database, one background worker and in-memory rate limits suit a small single-process installation. Before operating a larger multi-merchant service, follow [the production readiness plan](docs/production-readiness.md) for a production server, shared database, durable queue, persistent rate limits, and operations controls.

Docker option, after generating and editing `.env`:

```sh
docker compose up --build -d
```

Docker was not run here because Docker Desktop was not running. No production deployment is included.

## WordPress plugin installation on another site

1. Run the shared service with HTTPS.
2. Add the website in the Voca dashboard, selecting WordPress. Save its generated connection key; it is only shown once.
3. Upload `voca-agent-wordpress.zip` through **Plugins → Add New → Upload Plugin** and activate it.
4. Open **Settings → Voca Agent**. Enter the service address, website ID and connection key. Enable the guide and save.
5. The plugin checks the connection and automatically sends published content in small batches. Inspect indexing in the service dashboard.

Set `_voca_exclude=1` on a post to exclude it. On low-traffic sites configure system cron to run WordPress scheduled events; otherwise background tasks wait for visits. WordPress multisite, multilingual plugin mappings and subdirectory installations need separate compatibility testing.

The local WordPress development exception is limited to an explicitly listed `.local` site and a loopback service. Set `VOCA_LOCAL_DEV_HOSTS` only for a local development environment; leave it empty for production. It does not enable private-network crawling.

## Shopify app and theme extension

Detailed steps are in [shopify/README.md](shopify/README.md). Fill in app registration values and service secrets, deploy the theme extension with Shopify CLI, authorize the store from Voca, then enable the app embed in the theme editor. No theme source editing is required.

The service uses the standalone OAuth flow, validates callback HMAC and browser-bound state, keeps credentials encrypted, renews expiring offline tokens, paginates content, and verifies webhook signatures. There is no merchant billing, embedded admin session layer, customer account access or cart mutation in this first version.

This is application source for development installation, not an approved Shopify App Store listing. The dashboard is currently an operator administration surface; it does not provide independent merchant accounts. Marketplace onboarding and merchant-specific administration remain future work.

## Webflow app

Detailed steps are in [webflow/README.md](webflow/README.md). Register a Webflow Data Client app, configure its OAuth credentials on the service, add your published website and Webflow site ID in Voca, then connect it.

The application registers the v1 widget with an integrity hash and applies it in the site footer, preserving existing scripts. **Publish the Webflow site yourself** after installation or removal: Webflow publishing also publishes other staged changes. The service never silently publishes those changes.

`webflow/app-config.json` is a registration worksheet, not an importable marketplace manifest. The app has not been registered, reviewed or tested against a real Webflow account here.

## AI and voice

The backend uses the OpenAI Responses API and multilingual embeddings. AI facts come from retrieved excerpts belonging to that website; generated source IDs are checked against those excerpts before links are shown. Conversations are sent statelessly with `store:false`; visitor transcripts are not persisted by Voca. The selected provider still processes questions, recent conversation context and retrieved content under its API data policies. Update your site privacy notice accordingly.

Default models are configurable (`OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`). Model availability and API billing depend on your OpenAI account. Keys remain server-side; public widget IDs grant no write or admin access. Saving the key in the admin dashboard automatically queues embedding preparation. Use a model your API account can access.

Voice uses the browser’s speech recognition and speech synthesis. Visitors initiate microphone access explicitly. Recognition support, accent handling and installed voices vary by browser and device. Text chat works without voice support. This is turn-based voice chat, not a low-latency interruptible speech-to-speech agent.

## Verification

- 29 backend tests passed: tenant isolation, connection keys, encrypted credentials, snapshot retries, failed-index preservation, source-link validation, OAuth state, token refresh, webhook signatures and HTTP access controls.
- WordPress PHP syntax passed using PHP 8.2.29.
- Widget tests passed: open/close, question submission, response escaping, language changes, unsupported voice fallback and duplicate-load prevention.
- Shopify Liquid rendered correctly with service URLs both with and without a trailing slash; empty configuration does not insert the widget.
- Actual WordPress activation and first content import passed on your local site. The widget was opened and checked in a browser.
- Live AI answer quality, microphone capture, Shopify OAuth installation and Webflow custom-code installation are not verified without the corresponding credentials/accounts.

Run backend tests:

```sh
cd backend
python -m unittest discover -s tests -v
```

## References

- [WordPress plugin handbook](https://developer.wordpress.org/plugins/)
- [Shopify theme app extensions](https://shopify.dev/docs/apps/build/online-store/theme-app-extensions)
- [Shopify standalone app authorization](https://shopify.dev/docs/apps/build/authentication-authorization/authenticate-standalone-apps)
- [Webflow OAuth](https://developers.webflow.com/data/reference/oauth-app)
- [Webflow custom-code lifecycle](https://developers.webflow.com/data/docs/working-with-custom-code)
- [OpenAI text generation](https://developers.openai.com/api/docs/guides/text)
- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)


## Gemini fallback

In the dashboard, open **AI connection** and save a Gemini API key from https://aistudio.google.com/app/apikey. Leave the OpenAI key field blank to keep its saved value. Keys are encrypted on the backend; neither is returned to the browser.

OpenAI is preferred for new indexes. OpenAI limit errors (429), unavailable models (404), temporary service failures (500/502/503/504), and exhausted network retries trigger Gemini fallback when configured. If answer generation alone fails, Gemini uses the already-retrieved excerpts. If search embeddings fail, a Gemini index is built; visitors may briefly see a message asking them to retry while this finishes. Indexes already built with Gemini retain Gemini search embeddings. Answer generation is routed independently, allowing OpenAI or Gemini answers using the same retrieved excerpts. No incompatible vectors are compared. Authentication and permission failures are reported without silently switching providers. Gemini's own quota errors are shown clearly.

Saving only a Gemini key also works. The default models are `gemini-3.1-flash-lite` for answers and `gemini-embedding-001` for search. Gemini receives website content for indexing and visitor questions/history for answers. Its own account limits and billing apply.

Validation: automated tests cover indexing, API behavior, tenant separation, fallback, retrieval cutoff and citation requirements. A real Gemini response was previously checked with fictional product content; provider performance and answer quality should be evaluated on your own approved test corpus.


## Reliability and setup update — 2 October 2026

After signing in, use **Get your guide ready** to add a website, configure AI, import content, and test an answer. The existing administrator key remains required for dashboard access.

- **AI connection → Check OpenAI / Check Gemini** uses a fictional example to test both embeddings and answer generation. Save settings first. Checks may incur provider usage and never send website excerpts.
- Select a website and use **Test your guide**. Choose a language and confirm sending the question and relevant excerpts to the configured provider. The result includes actual answer provider, model, timing, cited sources, and retrieved excerpts. Questions and test results are held in browser memory only; refreshing clears them.
- **Preview indexed text** shows what the index contains for a document. Only authenticated administrators can view these previews; long documents are shortened in the preview.
- Authoritative content removals now run before embedding requests. If AI indexing fails, confirmed removed documents stay removed. Partial crawls retain pages whose removal has not been confirmed. A request already being answered is checked again before returning its result; if its source content changed, the visitor is asked to retry. Removal takes effect when the sync job processes the authoritative update.
- Answer-provider fallback is independent of the search provider. Existing Gemini indexes need not be rebuilt merely because answer generation changes providers. Authentication failures remain explicit. Gemini-only installations still depend on Google's availability.
- AI answer calls share a 50-second provider-request budget, with shorter bounded attempts. Provider errors distinguish quota, unavailable models, authentication, and temporary outages. OS-level DNS lookup and database contention are not covered by a hard cancellation guarantee.
- Duplicate queued/running embedding jobs are coalesced.

The production hosting and live Shopify/Webflow setup still need their own deployment and installation work. This update does not add customer accounts, billing, continuous voice, analytics, or FAQ editing.

## Branding, contact handoff and usage
Open a website in the dashboard to customize its guide name, welcome message, launcher text, color and left/right position. Add an HTTPS contact page or mailto email address to enable the contact button. This opens your contact destination; it does not provide live chat or forward transcripts. Refresh the website after saving.

The default retrieval relevance cutoff is `0.18` cosine similarity (`VOCA_MIN_RELEVANCE_SCORE` can be set from 0 to 1). This is a conservative starting value; evaluate representative questions and tune it for your content and embedding model. Answers without a retrieved match or a source citation are replaced with a localized “not found” response. The usage dashboard shows the last 30 UTC days of questions reaching AI, answers, errors, uncited answers, average successful response time, provider counts and contact clicks. It stores daily totals only, without messages, visitor IDs or IP addresses. Clicks do not mean completed contacts. Counts start with this update; admin answer tests are excluded. Aggregates older than 90 days are removed when new activity is recorded.

Updated integrations use widget v2. Widget v1 remains available unchanged for previously registered Webflow integrity hashes. Existing Webflow installations must reinstall the guide and publish to adopt v2. Update the WordPress plugin or Shopify theme extension to adopt the new widget.
