import { bookmarkColor } from './bookmarkColors.js';

export function suggestionProvider(engine) {
  return ['g', 'd', 'y'].includes(engine) ? engine : null;
}

export function parseQuery(input, engines, defaultEngine) {
  const value = input.trim();
  const [prefix, ...rest] = value.split(/\s+/);
  const explicit = prefix.startsWith('!') && Object.hasOwn(engines, prefix.slice(1));
  return { query: explicit ? rest.join(' ') : value, engine: explicit ? prefix.slice(1) : defaultEngine, explicit };
}

export function isUrl(value) {
  return /^https?:\/\//i.test(value) || /^www\./i.test(value)
    || /^([\w-]+\.)+[a-z]{2,}([/:?#].*)?$/i.test(value)
    || /^localhost(:\d+)?([/].*)?$/i.test(value)
    || /^(\d{1,3}\.){3}\d{1,3}(:\d+)?([/].*)?$/.test(value);
}

export function findBookmarks(tabs, input) {
  const query = input.normalize('NFKC').toLocaleLowerCase().trim();
  const terms = query.split(/\s+/).filter(Boolean);
  const found = [];
  for (const tab of tabs) for (const category of tab.categories) for (const [index, link] of category.links.entries()) {
    const name = link.name.normalize('NFKC').toLocaleLowerCase();
    const url = link.url.normalize('NFKC').toLocaleLowerCase();
    const context = `${name} ${url} ${tab.name} ${category.name}`.normalize('NFKC').toLocaleLowerCase();
    if (!terms.every(term => context.includes(term))) continue;
    const score = query ? (name === query ? 5 : name.startsWith(query) ? 4 : name.includes(query) ? 3 : url.includes(query) ? 2 : 1) : 0;
    found.push({ ...link, displayColor: bookmarkColor(link, index), tabName: tab.name, categoryName: category.name, score });
  }
  return found.sort((a,b) => b.score - a.score);
}

export function webUrl(engines, engine, query) {
  return engines[engine][0] + encodeURIComponent(query);
}
