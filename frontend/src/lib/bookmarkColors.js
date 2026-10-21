// The original startpage's category color order, expressed in theme variables.
const sequence = ['green', 'peach', 'red', 'blue', 'mauve'];

export function bookmarkColor(link, index = 0) {
  if (/^#[a-f\d]{6}$/i.test(link?.icon_color || '')) return link.icon_color;
  const position = Number.isInteger(index) && index >= 0 ? index : 0;
  return `var(--${sequence[position % sequence.length]})`;
}
