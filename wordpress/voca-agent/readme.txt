=== Voca Website AI Agent ===
Contributors: voca
Tags: ai, chatbot, voice, woocommerce
Requires at least: 6.2
Tested up to: 7.1.2
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later

A multilingual voice and text guide powered by your website’s published content.

== Installation ==
1. Deploy the included Voca service and configure its AI key.
2. Add this website in the Voca dashboard as WordPress. Save its website ID and connection key.
3. Upload the plugin ZIP and activate it.
4. In Settings > Voca Agent, enter the HTTPS service address, website ID and connection key.
5. Enable the visitor guide, then Save and sync.
6. Content sends automatically in batches. Track AI indexing in the service dashboard.

== Content and privacy ==
Published public post types, pages, posts and visible WooCommerce products are imported. Drafts, password-protected pages, private posts, attachments, orders and customer records are excluded. Set _voca_exclude=1 on a post to exclude it.
The plugin sends content to the agent service configured by the administrator. The service sends relevant excerpts and visitor questions to OpenAI when answering. Browsers may send audio to their speech recognition provider after visitors explicitly press the microphone button.
No AI or platform secret is placed in the public widget. An administrator supplies a private content-sync connection key.
On low-traffic sites, use a system cron to run WordPress scheduled events reliably.

== Limitations ==
This release passed activation, published-content import and widget checks on a local WordPress 7.1.2 site using PHP 8.2.29. It reads supported Elementor text fields. Other builder metadata, PDFs and text inside images require additional importers. Shortcodes are stripped instead of executed to avoid sending private dynamic data.

== Uninstall ==
Deactivate or delete the plugin to stop its widget and scheduled imports. Delete the site in the Voca service dashboard to erase its server-side knowledge.
