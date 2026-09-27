/**
 * slots.mjs — the one slot vocabulary shared by the catalog, the overlay and the planner.
 * A slot is WHAT a thing is for (hero, pricing, button), never what it is called upstream.
 */
export const BLOCK_SLOTS = ['navbar', 'hero', 'logo-cloud', 'features', 'content', 'stats', 'integrations',
  'testimonials', 'pricing', 'comparison', 'team', 'faq', 'cta', 'contact', 'footer', 'login', 'signup',
  'forgot-password', 'blog', 'sidebar', 'dashboard'];

export const UI_SLOTS = ['button', 'badge', 'card', 'input', 'textarea', 'select', 'checkbox', 'switch',
  'radio-group', 'slider', 'tabs', 'accordion', 'dialog', 'sheet', 'popover', 'tooltip', 'dropdown-menu',
  'avatar', 'table', 'breadcrumb', 'pagination', 'progress', 'skeleton', 'toast', 'command', 'calendar',
  'label', 'separator', 'navigation-menu', 'carousel', 'chart'];

export const EFFECT_SLOTS = ['text-effect', 'background', 'marquee', 'border-effect', 'cursor', 'number-ticker'];

export const TAILARK_CATEGORY = {
  'hero-section': 'hero', 'call-to-action': 'cta', faqs: 'faq', features: 'features', footer: 'footer',
  pricing: 'pricing', testimonials: 'testimonials', 'logo-cloud': 'logo-cloud', stats: 'stats', team: 'team',
  contact: 'contact', content: 'content', integrations: 'integrations', login: 'login', 'sign-up': 'signup',
  'forgot-password': 'forgot-password', comparator: 'comparison', 'blog-blocks': 'blog', bento: 'features',
  header: 'navbar',
};

const NAME_RULES = [
  // not slots: groups of controls, demos, hooks (a null rule stops the scan)
  // (and a vendor's own branded button — "Open in v0" — is not a button for anyone else's site)
  [/(button|toggle|input)-group|input-otp|native-select|-demo$|^use-|^v0-/, null],
  [/^(login|sign-?in)/, 'login'], [/^(signup|sign-?up|register)/, 'signup'], [/^sidebar/, 'sidebar'],
  [/^dashboard/, 'dashboard'], [/^calendar/, 'calendar'], [/(^|-)hero/, 'hero'], [/pricing/, 'pricing'],
  [/(^|-)(faq|faqs)(-|$)/, 'faq'], [/footer/, 'footer'], [/(navbar|header|navigation-bar|nav-bar)/, 'navbar'],
  [/testimonial/, 'testimonials'], [/(^|-)cta(-|$)|call-to-action/, 'cta'], [/(^|-)features?(-|$)|bento/, 'features'],
  [/(^|-)stats?(-|$)/, 'stats'], [/(^|-)team(-|$)/, 'team'], [/contact/, 'contact'], [/logo-?cloud|logos/, 'logo-cloud'],
  [/hover-?card/, 'popover'], [/tweet/, 'embed'], [/button/, 'button'], [/badge/, 'badge'], [/(^|-)card(-|$)/, 'card'], [/textarea/, 'textarea'],
  [/(^|-)input(-|$)/, 'input'], [/(^|-)select(-|$)/, 'select'], [/checkbox/, 'checkbox'], [/switch|toggle/, 'switch'],
  [/radio/, 'radio-group'], [/slider/, 'slider'], [/(^|-)tabs?(-|$)/, 'tabs'], [/accordion/, 'accordion'],
  [/dialog|modal/, 'dialog'], [/(^|-)sheet(-|$)|drawer/, 'sheet'], [/popover/, 'popover'], [/tooltip/, 'tooltip'],
  [/dropdown/, 'dropdown-menu'], [/avatar/, 'avatar'], [/(^|-)table(-|$)/, 'table'], [/breadcrumb/, 'breadcrumb'],
  [/pagination/, 'pagination'], [/progress/, 'progress'], [/skeleton/, 'skeleton'], [/toast|sonner/, 'toast'],
  [/command/, 'command'], [/marquee/, 'marquee'], [/number-ticker|counter/, 'number-ticker'],
  [/(text|typing|word|letter|gradient-text|sparkles-text|hyper|morphing|spinning-text|aurora-text|line-shadow|highlighter)/, 'text-effect'],
  [/(grid|pattern|particles|ripple|meteors|beam|globe|background|warp|flickering|dots|retro|aurora|noise)/, 'background'],
  [/(border|shine|glow|magic-card|neon)/, 'border-effect'], [/cursor|pointer/, 'cursor'],
  [/(^|-)label(-|$)/, 'label'], [/separator/, 'separator'], [/navigation-menu/, 'navigation-menu'], [/carousel/, 'carousel'],
  [/chart/, 'chart'],
];

export function slotFromName(name) {
  const n = String(name || '').toLowerCase();
  for (const [re, slot] of NAME_RULES) if (re.test(n)) return slot;
  return null;
}

export function kindOf(slot) {
  if (BLOCK_SLOTS.includes(slot)) return 'block';
  if (UI_SLOTS.includes(slot)) return 'ui';
  if (EFFECT_SLOTS.includes(slot)) return 'effect';
  return 'other';
}

/** Slots a click on one slot may be swapped with (like-for-like, plus close cousins). */
export const COMPATIBLE = {
  hero: ['hero'], cta: ['cta', 'hero'], features: ['features', 'content'], content: ['content', 'features'],
  'logo-cloud': ['logo-cloud', 'marquee'], navbar: ['navbar'], footer: ['footer'], pricing: ['pricing'],
  testimonials: ['testimonials'], faq: ['faq'], stats: ['stats'], team: ['team'], contact: ['contact'],
  login: ['login'], signup: ['signup'], integrations: ['integrations'], comparison: ['comparison', 'pricing'],
  button: ['button'], badge: ['badge'], card: ['card'], input: ['input'], 'text-effect': ['text-effect'],
};
