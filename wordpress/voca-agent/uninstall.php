<?php
if (!defined('WP_UNINSTALL_PLUGIN')) { exit; }
foreach (array('voca_agent_daily','voca_agent_batch','voca_agent_start_sync') as $hook) { wp_clear_scheduled_hook($hook); }
foreach (array('voca_agent_settings','voca_agent_sync_state','voca_agent_sync_report') as $option) { delete_option($option); }
delete_transient('voca_agent_batch_lock');
// Also delete the website in your Voca dashboard to remove its server-side index.
