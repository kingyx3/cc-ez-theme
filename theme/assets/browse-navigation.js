(() => {
  'use strict';

  const dataElement = document.getElementById('BrowseCollectionHierarchy');
  const rootItems = Array.from(document.querySelectorAll('[data-browse-root]'));

  if (!dataElement || rootItems.length === 0) return;

  const normalizeId = (value) => {
    if (value === null || value === undefined) return '';
    return String(value).trim();
  };

  const normalizeHandle = (value) => {
    if (!value) return '';
    return decodeURIComponent(String(value))
      .split('?')[0]
      .replace(/^\/+|\/+$/g, '')
      .toLowerCase();
  };

  const isLocked = (value) => value === true || value === 1 || value === '1' || String(value).toLowerCase() === 'true';

  let collections;
  try {
    collections = JSON.parse(dataElement.textContent);
  } catch (error) {
    console.error('[Browse navigation] EasyStore collection data is invalid JSON.', error);
    rootItems.forEach((item) => { item.dataset.browseStatus = 'invalid-data'; });
    return;
  }

  if (!Array.isArray(collections)) collections = Object.values(collections || {});

  const records = collections
    .filter((collection) => collection && !isLocked(collection.is_locked))
    .map((collection, index) => ({
      id: normalizeId(collection.id),
      parentId: normalizeId(collection.parent_id),
      title: String(collection.title || collection.name || ''),
      handle: normalizeHandle(collection.handle),
      position: Number.isFinite(Number(collection.position)) ? Number(collection.position) : index,
      sourceIndex: index,
    }))
    .filter((collection) => collection.id && collection.handle && collection.title);

  const byHandle = new Map();
  const childrenByParentId = new Map();

  records.forEach((collection) => {
    byHandle.set(collection.handle, collection);
    if (!collection.parentId) return;
    const siblings = childrenByParentId.get(collection.parentId) || [];
    siblings.push(collection);
    childrenByParentId.set(collection.parentId, siblings);
  });

  childrenByParentId.forEach((siblings) => {
    siblings.sort((left, right) => left.position - right.position || left.sourceIndex - right.sourceIndex);
  });

  const collectionUrl = (collection) => `/collections/${encodeURIComponent(collection.handle)}`;

  const indicator = () => {
    const span = document.createElement('span');
    span.className = 'browse-menu__indicator';
    span.setAttribute('aria-hidden', 'true');
    span.textContent = '›';
    return span;
  };

  const link = (collection, mode, label = collection.title) => {
    const anchor = document.createElement('a');
    anchor.href = collectionUrl(collection);
    anchor.textContent = label;
    anchor.className = mode === 'mobile'
      ? 'menu-drawer__menu-item list-menu__item link link--text focus-inset'
      : 'header__menu-item list-menu__item link link--text focus-inset caption-large';
    return anchor;
  };

  const desktopItem = (collection, ancestors = new Set()) => {
    const item = document.createElement('li');
    const anchor = link(collection, 'desktop');
    item.append(anchor);

    if (ancestors.has(collection.id)) return item;

    const children = childrenByParentId.get(collection.id) || [];
    if (children.length === 0) return item;

    item.classList.add('browse-menu__item--has-children');
    anchor.append(indicator());

    const submenu = document.createElement('ul');
    submenu.className = 'header__submenu browse-menu__flyout list-menu list-menu--disclosure motion-reduce';
    submenu.setAttribute('role', 'list');

    const nextAncestors = new Set(ancestors);
    nextAncestors.add(collection.id);
    children.forEach((child) => submenu.append(desktopItem(child, nextAncestors)));
    item.append(submenu);
    return item;
  };

  let submenuSequence = 0;

  const mobileItem = (collection, ancestors = new Set()) => {
    const item = document.createElement('li');
    const children = ancestors.has(collection.id) ? [] : (childrenByParentId.get(collection.id) || []);

    if (children.length === 0) {
      item.append(link(collection, 'mobile'));
      return item;
    }

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    const title = document.createElement('span');
    const submenu = document.createElement('div');
    const inner = document.createElement('div');
    const closeButton = document.createElement('button');
    const list = document.createElement('ul');
    const viewAllItem = document.createElement('li');
    const submenuId = `BrowseMobileSubmenu-${++submenuSequence}`;

    title.textContent = collection.title;
    summary.className = 'menu-drawer__menu-item list-menu__item link link--text focus-inset';
    summary.setAttribute('aria-controls', submenuId);
    summary.append(title, indicator());

    submenu.id = submenuId;
    submenu.className = 'menu-drawer__submenu motion-reduce';
    submenu.setAttribute('tabindex', '-1');
    inner.className = 'menu-drawer__inner-submenu';
    closeButton.type = 'button';
    closeButton.className = 'menu-drawer__close-button link link--text focus-inset';
    closeButton.textContent = `‹ ${collection.title}`;
    list.className = 'menu-drawer__menu list-menu';
    list.setAttribute('role', 'list');
    viewAllItem.append(link(collection, 'mobile', `View all ${collection.title}`));
    list.append(viewAllItem);

    const nextAncestors = new Set(ancestors);
    nextAncestors.add(collection.id);
    children.forEach((child) => list.append(mobileItem(child, nextAncestors)));

    inner.append(closeButton, list);
    submenu.append(inner);
    details.append(summary, submenu);
    item.append(details);
    return item;
  };

  let enhancedRoots = 0;
  let descendantCount = 0;

  rootItems.forEach((item) => {
    const mode = item.dataset.browseMode === 'mobile' ? 'mobile' : 'desktop';
    const handles = [item.dataset.browseLinkHandle, item.dataset.browseUrlHandle]
      .map(normalizeHandle)
      .filter(Boolean);
    const rootCollection = handles.map((handle) => byHandle.get(handle)).find(Boolean);

    if (!rootCollection) {
      item.dataset.browseStatus = 'unmatched-root';
      return;
    }

    const children = childrenByParentId.get(rootCollection.id) || [];
    if (children.length === 0) {
      item.dataset.browseStatus = 'no-descendants';
      return;
    }

    descendantCount += children.length;
    enhancedRoots += 1;
    item.dataset.browseStatus = 'enhanced';

    if (mode === 'mobile') {
      const enhanced = mobileItem(rootCollection);
      item.replaceChildren(...enhanced.childNodes);
      return;
    }

    item.classList.add('browse-menu__item--has-children');
    const rootAnchor = item.querySelector(':scope > a');
    if (rootAnchor) rootAnchor.append(indicator());

    const submenu = document.createElement('ul');
    submenu.className = 'header__submenu browse-menu__flyout list-menu list-menu--disclosure motion-reduce';
    submenu.setAttribute('role', 'list');
    children.forEach((child) => submenu.append(desktopItem(child, new Set([rootCollection.id]))));
    item.append(submenu);
  });

  document.dispatchEvent(new CustomEvent('browse-navigation:ready', {
    detail: {
      collectionCount: records.length,
      enhancedRoots,
      descendantCount,
    },
  }));

  if (enhancedRoots === 0) {
    console.warn('[Browse navigation] EasyStore returned no matching descendant relationships.', {
      collectionCount: records.length,
      rootHandles: rootItems.map((item) => [item.dataset.browseLinkHandle, item.dataset.browseUrlHandle]),
    });
  }
})();
