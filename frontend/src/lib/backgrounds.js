import { appUrl } from './navigation.js';

export function backgroundUrl(tab) {
  return tab?.background_id
    ? appUrl(`api/backgrounds/${encodeURIComponent(tab.background_id)}/content`)
    : '';
}
