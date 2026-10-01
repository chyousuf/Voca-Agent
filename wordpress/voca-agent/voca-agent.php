<?php
/**
 * Plugin Name: Voca Website AI Agent
 * Description: Automatically sync published WordPress and WooCommerce content to your Voca AI service and add a multilingual voice/text guide.
 * Version: 1.1.0
 * Requires at least: 6.2
 * Requires PHP: 7.4
 * Author: Voca
 * License: GPL-2.0-or-later
 * Text Domain: voca-agent
 */
if (!defined('ABSPATH')) { exit; }

final class Voca_Agent {
    const OPTION = 'voca_agent_settings';
    const STATE = 'voca_agent_sync_state';
    const REPORT = 'voca_agent_sync_report';

    public static function init() {
        add_action('admin_menu', array(__CLASS__, 'menu'));
        add_action('admin_post_voca_save', array(__CLASS__, 'save'));
        add_action('admin_post_voca_sync', array(__CLASS__, 'manual_sync'));
        add_action('wp_enqueue_scripts', array(__CLASS__, 'widget'));
        add_filter('script_loader_tag', array(__CLASS__, 'script_tag'), 10, 3);
        add_action('voca_agent_start_sync', array(__CLASS__, 'start_sync'));
        add_action('voca_agent_batch', array(__CLASS__, 'batch'));
        add_action('voca_agent_daily', array(__CLASS__, 'request_sync'));
        add_action('save_post', array(__CLASS__, 'changed'), 20, 3);
        add_action('deleted_post', array(__CLASS__, 'request_sync'));
        add_action('trashed_post', array(__CLASS__, 'request_sync'));
        add_action('untrashed_post', array(__CLASS__, 'request_sync'));
        add_action('updated_post_meta', array(__CLASS__, 'meta_changed'), 20, 4);
        add_action('updated_option', array(__CLASS__, 'option_changed'), 20, 3);
        add_action('woocommerce_update_product', array(__CLASS__, 'request_sync'));
        add_action('woocommerce_product_set_stock', array(__CLASS__, 'request_sync'));
    }
    public static function activate() {
        if (!wp_next_scheduled('voca_agent_daily')) { wp_schedule_event(time() + 60, 'daily', 'voca_agent_daily'); }
        self::request_sync();
    }
    public static function deactivate() {
        foreach (array('voca_agent_daily','voca_agent_batch','voca_agent_start_sync') as $hook) { wp_clear_scheduled_hook($hook); }
        delete_transient('voca_agent_batch_lock');
    }
    private static function settings() { return get_option(self::OPTION, array()); }
    private static function configured() {
        $s = self::settings();
        return !empty($s['service']) && !empty($s['site']) && !empty($s['key']);
    }
    private static function local_service($url) {
        $p = wp_parse_url($url);
        return function_exists('wp_get_environment_type') && wp_get_environment_type() === 'local'
            && $p && $p['scheme'] === 'http' && in_array($p['host'], array('127.0.0.1','localhost'), true)
            && !empty($p['port']) && $p['port'] >= 1024 && $p['port'] <= 65535;
    }
    private static function remote($method, $url, $args) {
        if (self::local_service($url)) {
            return $method === 'POST' ? wp_remote_post($url, $args) : wp_remote_get($url, $args);
        }
        return $method === 'POST' ? wp_safe_remote_post($url, $args) : wp_safe_remote_get($url, $args);
    }
    public static function menu() { add_options_page('Voca Agent', 'Voca Agent', 'manage_options', 'voca-agent', array(__CLASS__, 'screen')); }
    public static function screen() {
        if (!current_user_can('manage_options')) { return; }
        $s = self::settings(); $report = get_option(self::REPORT, array());
        echo '<div class="wrap"><h1>Voca Website AI Agent</h1><p>Connect your website once. Published pages, posts, public content types and visible WooCommerce products sync automatically.</p>';
        echo '<form method="post" action="' . esc_url(admin_url('admin-post.php')) . '"><input type="hidden" name="action" value="voca_save">';
        wp_nonce_field('voca_save');
        echo '<table class="form-table"><tbody>';
        $fields = array('service' => 'Agent service address (HTTPS)', 'site' => 'Website ID', 'key' => 'Connection key');
        foreach ($fields as $field => $label) {
            $value = $field === 'key' ? '' : (isset($s[$field]) ? $s[$field] : '');
            echo '<tr><th><label for="voca-' . esc_attr($field) . '">' . esc_html($label) . '</label></th><td><input class="regular-text" id="voca-' . esc_attr($field) . '" name="' . esc_attr($field) . '" type="' . ($field === 'key' ? 'password' : 'text') . '" value="' . esc_attr($value) . '" autocomplete="off">';
            if ($field === 'key' && !empty($s['key'])) { echo '<p class="description">A connection key is saved. Leave blank to keep it.</p>'; }
            echo '</td></tr>';
        }
        echo '<tr><th>Visitor guide</th><td><label><input type="checkbox" name="enabled" value="1" ' . checked(!empty($s['enabled']), true, false) . '> Show the voice and text guide</label></td></tr></tbody></table>';
        submit_button('Save and sync'); echo '</form>';
        if (self::configured()) {
            echo '<h2>Content sync</h2><p>' . esc_html(isset($report['message']) ? $report['message'] : 'Waiting for the first sync.') . '</p>';
            echo '<form method="post" action="' . esc_url(admin_url('admin-post.php')) . '"><input type="hidden" name="action" value="voca_sync">';
            wp_nonce_field('voca_sync'); submit_button('Refresh content', 'secondary'); echo '</form>';
        }
        echo '<h2>What gets shared</h2><p>Only published visitor-facing content is sent to your configured agent service. Password-protected pages, drafts, private posts, orders, customer data and hidden products are excluded. The service sends relevant excerpts and visitor questions to its AI provider. Voice input uses the visitor’s browser speech service.</p><p>Sync runs through WordPress scheduled tasks. For quiet websites, configure a real cron job so updates run regularly. For content you want excluded, set the post custom field <code>_voca_exclude</code> to <code>1</code>.</p></div>';
    }
    public static function save() {
        if (!current_user_can('manage_options')) { wp_die('Access denied.', '', array('response'=>403)); }
        check_admin_referer('voca_save');
        $old = self::settings();
        $service = untrailingslashit(esc_url_raw(wp_unslash(isset($_POST['service']) ? $_POST['service'] : '')));
        $site = sanitize_text_field(wp_unslash(isset($_POST['site']) ? $_POST['site'] : ''));
        $key = trim(wp_unslash(isset($_POST['key']) ? $_POST['key'] : ''));
        if (!$key && isset($old['key'])) { $key = $old['key']; }
        $parts = wp_parse_url($service);
        if (!$parts || ($parts['scheme'] !== 'https' && !self::local_service($service)) || !empty($parts['user']) || !empty($parts['pass']) || !empty($parts['query']) || !empty($parts['fragment']) || (!empty($parts['path']) && $parts['path'] !== '/') || !preg_match('/^site_[a-f0-9]{32}$/', $site) || strlen($key) < 32 || strlen($key) > 128) {
            wp_die('Enter a valid HTTPS service address, website ID and connection key.');
        }
        $candidate = array('service'=>$service,'site'=>$site,'key'=>$key,'enabled'=>isset($_POST['enabled']) ? 1 : 0);
        $response = self::remote('GET', $service . '/api/plugin/status?site=' . rawurlencode($site), array('timeout'=>15,'headers'=>array('Authorization'=>'Bearer ' . $key)));
        if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) { wp_die('Could not connect to the agent service. Check the address, website ID and connection key.'); }
        $remote = json_decode(wp_remote_retrieve_body($response), true);
        if (empty($remote['origin']) || untrailingslashit($remote['origin']) !== untrailingslashit(home_url())) { wp_die('The website address in the agent dashboard must match this WordPress website.'); }
        update_option(self::OPTION, $candidate, false);
        self::request_sync();
        wp_safe_redirect(admin_url('options-general.php?page=voca-agent')); exit;
    }
    public static function manual_sync() {
        if (!current_user_can('manage_options')) { wp_die('Access denied.', '', array('response'=>403)); }
        check_admin_referer('voca_sync'); self::request_sync();
        wp_safe_redirect(admin_url('options-general.php?page=voca-agent')); exit;
    }
    public static function changed($id, $post, $update) {
        if (wp_is_post_revision($id) || wp_is_post_autosave($id) || $post->post_type === 'attachment') { return; }
        $type = get_post_type_object($post->post_type);
        if ($type && $type->public) { self::request_sync(); }
    }
    public static function meta_changed($meta_id, $post_id, $meta_key, $value) {
        if ($meta_key === '_voca_exclude') { self::request_sync(); }
    }
    public static function option_changed($name, $old, $new) {
        if (in_array($name, array('blogname','blogdescription','page_on_front','page_for_posts','woocommerce_currency'), true)) { self::request_sync(); }
    }
    public static function request_sync() {
        if (!self::configured()) { return; }
        $state = get_option(self::STATE, array());
        if (!empty($state)) { $state['restart'] = true; update_option(self::STATE, $state, false); }
        if (!wp_next_scheduled('voca_agent_start_sync')) { wp_schedule_single_event(time() + 20, 'voca_agent_start_sync'); }
    }
    private static function send($body) {
        $s = self::settings(); $body['site'] = $s['site'];
        $response = self::remote('POST', $s['service'] . '/api/plugin/sync', array('timeout'=>30,'headers'=>array('Authorization'=>'Bearer ' . $s['key'],'Content-Type'=>'application/json'),'body'=>wp_json_encode($body),'data_format'=>'body'));
        if (is_wp_error($response)) { return false; }
        return wp_remote_retrieve_response_code($response) === 202;
    }
    private static function report($message) { update_option(self::REPORT, array('message'=>$message,'updated'=>time()), false); }
    public static function start_sync() {
        if (!self::configured()) { return; }
        if (get_transient('voca_agent_batch_lock')) { wp_schedule_single_event(time()+40, 'voca_agent_start_sync'); return; }
        $previous = get_option(self::STATE, array());
        if (!empty($previous['run'])) { self::send(array('run_id'=>$previous['run'],'documents'=>array(),'abort'=>true)); }
        $types = get_post_types(array('public'=>true), 'names');
        $types = array_values(array_diff($types, array('attachment')));
        // Persist a numeric cursor only; loading every post ID at once can exhaust PHP memory on large sites.
        $state = array('run'=>str_replace('-', '', wp_generate_uuid4()),'offset'=>0,'sent'=>0,'restart'=>false,'retry'=>0);
        update_option(self::STATE, $state, false); self::report('Import queued. Published content is being sent in small batches.');
        wp_clear_scheduled_hook('voca_agent_batch'); wp_schedule_single_event(time()+1, 'voca_agent_batch');
    }
    private static function export_post($id) {
        $post = get_post($id);
        if (!$post || $post->post_status !== 'publish' || $post->post_password || get_post_meta($id, '_voca_exclude', true)) { return null; }
        $text = wp_strip_all_tags(strip_shortcodes($post->post_content)) . "\n" . wp_strip_all_tags($post->post_excerpt);
        $elementor = get_post_meta($id, '_elementor_data', true);
        if (is_string($elementor)) { $elementor = json_decode($elementor, true); }
        if (is_array($elementor)) { $text .= "\n" . self::elementor_text($elementor); }
        $kind = $post->post_type;
        if ($kind === 'product' && function_exists('wc_get_product')) {
            $product = wc_get_product($id);
            if (!$product || !$product->is_visible()) { return null; }
            $text .= "\nPrice: " . wp_strip_all_tags($product->get_price_html()) . ' ' . get_woocommerce_currency() . '. Stock: ' . $product->get_stock_status() . '. Check the product page for current price and availability.';
            foreach ($product->get_attributes() as $attribute) {
                if (!$attribute->get_visible()) { continue; }
                $values = $attribute->is_taxonomy() ? wc_get_product_terms($id, $attribute->get_name(), array('fields'=>'names')) : $attribute->get_options();
                if (!is_wp_error($values)) { $text .= "\n" . wc_attribute_label($attribute->get_name()) . ': ' . implode(', ', $values); }
            }
        }
        $text = function_exists('mb_substr') ? mb_substr($text, 0, 50000) : substr($text, 0, 50000);
        return array('id'=>'wp:' . $id,'url'=>get_permalink($id),'title'=>get_the_title($id),'text'=>$text,'kind'=>$kind);
    }
    private static function elementor_text($elements, $depth = 0) {
        if ($depth > 25) { return ''; }
        $allowed = array('title','editor','text','description','button_text','html','prefix','suffix','tab_title','tab_content','testimonial_content','testimonial_name','faq_question','faq_answer','heading','label','content','title_text','description_text');
        $result = '';
        foreach ($elements as $key => $value) {
            if (is_array($value)) { $result .= self::elementor_text($value, $depth + 1); }
            elseif (is_string($key) && in_array($key, $allowed, true) && is_string($value)) {
                $result .= wp_strip_all_tags(strip_shortcodes($value)) . "\n";
            }
        }
        return $result;
    }
    public static function batch() {
        if (!self::configured() || get_transient('voca_agent_batch_lock')) { return; }
        set_transient('voca_agent_batch_lock', 1, 90);
        try {
            $state = get_option(self::STATE, array());
            if (empty($state)) { return; }
            if (!empty($state['restart'])) { self::start_sync_after_batch(); return; }
            $docs = array();
            if ($state['offset'] === 0) {
                $docs[] = array('id'=>'wp:site','url'=>home_url('/'),'title'=>get_bloginfo('name'),'text'=>get_bloginfo('name') . "\n" . get_bloginfo('description'),'kind'=>'site');
            }
            $types = array_values(array_diff(get_post_types(array('public'=>true), 'names'), array('attachment')));
            $ids = get_posts(array('post_type'=>$types,'post_status'=>'publish','posts_per_page'=>10,'offset'=>$state['offset'],'fields'=>'ids','orderby'=>'ID','order'=>'ASC','has_password'=>false,'suppress_filters'=>false));
            foreach ($ids as $id) { $doc = self::export_post($id); if ($doc) { $docs[] = $doc; } }
            $next = $state['offset'] + count($ids); $final = count($ids) < 10;
            $fresh = get_option(self::STATE, array());
            if (!empty($fresh['restart']) || $fresh['run'] !== $state['run']) { self::start_sync_after_batch(); return; }
            if (!self::send(array('run_id'=>$state['run'],'documents'=>$docs,'final'=>$final))) {
                $state['retry']++; update_option(self::STATE, $state, false);
                self::report('The service could not accept the last batch. Retrying automatically.');
                wp_schedule_single_event(time()+min(900, 30 * $state['retry']), 'voca_agent_batch'); return;
            }
            $fresh = get_option(self::STATE, array());
            if (!empty($fresh['restart'])) { self::start_sync_after_batch(); return; }
            $state['offset'] = $next; $state['sent'] += count($docs); $state['retry'] = 0;
            if ($final) { delete_option(self::STATE); self::report($state['sent'] . ' documents sent. The service is preparing AI search. Check its dashboard for indexing status.'); }
            else { update_option(self::STATE, $state, false); self::report($state['sent'] . ' documents sent so far.'); wp_schedule_single_event(time()+5, 'voca_agent_batch'); }
        } finally { delete_transient('voca_agent_batch_lock'); }
    }
    private static function start_sync_after_batch() {
        wp_clear_scheduled_hook('voca_agent_start_sync'); wp_schedule_single_event(time()+2, 'voca_agent_start_sync');
    }
    public static function widget() {
        $s = self::settings();
        if (!self::configured() || empty($s['enabled']) || is_admin() || is_preview()) { return; }
        wp_enqueue_script('voca-agent-widget', $s['service'] . '/widget/v2/widget.js', array(), '1.1.0', true);
    }
    public static function script_tag($tag, $handle, $src) {
        if ($handle !== 'voca-agent-widget') { return $tag; }
        $s = self::settings();
        return '<script defer src="' . esc_url($src) . '" data-voca-api="' . esc_attr($s['service']) . '" data-voca-site="' . esc_attr($s['site']) . '"></script>';
    }
}
Voca_Agent::init();
register_activation_hook(__FILE__, array('Voca_Agent', 'activate'));
register_deactivation_hook(__FILE__, array('Voca_Agent', 'deactivate'));
