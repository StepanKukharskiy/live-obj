<script lang="ts">
  type SchemaDef = {
    type?: string;
    default?: unknown;
    enum?: unknown[];
    options?: unknown[];
    properties?: Record<string, SchemaDef>;
    description?: string;
  };

  export let key = '';
  export let schemaDef: SchemaDef | null = null;
  export let value: unknown = undefined;
  export let onChange: (v: unknown) => void = () => {};
  export let depth = 0;

  function toReadableLabel(input: unknown) {
    if (!input) return '';
    return String(input)
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .replace(/[-_.]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/^./, (char) => char.toUpperCase());
  }

  function isColorKey(k: unknown) {
    return k === 'color' || (typeof k === 'string' && k.toLowerCase().endsWith('color'));
  }

  function valToHex(v: unknown) {
    if (typeof v === 'number') return '#' + Math.round(v).toString(16).padStart(6, '0');
    if (typeof v === 'string') {
      if (/^#[0-9a-fA-F]{3,8}$/.test(v)) return v;
      try {
        const c = document.createElement('canvas').getContext('2d');
        if (!c) return '#888888';
        c.fillStyle = v;
        return c.fillStyle;
      } catch {
        return '#888888';
      }
    }
    return '#888888';
  }

  function resolveType(k: string, sd: SchemaDef | null, v: unknown) {
    const d = sd || {};
    if (d.type === 'color' || isColorKey(k)) return 'color';
    if (d.type === 'number') return 'number';
    if (d.type === 'boolean') return 'boolean';
    if (d.type === 'object' && d.properties) return 'object';
    if (d.type === 'array' || d.type === 'polygon') return 'array';
    if (d.type === 'string') return 'string';
    const actual = v !== undefined ? v : d.default;
    // Detect variable references (strings starting with $)
    if (typeof actual === 'string' && actual.startsWith('$')) return 'expr';
    if (actual && typeof actual === 'object' && !Array.isArray(actual) && 'expr' in actual && (actual as { expr?: unknown }).expr != null) return 'expr';
    if (typeof actual === 'number') return 'number';
    if (typeof actual === 'boolean') return 'boolean';
    if (typeof actual === 'string') return 'string';
    if (Array.isArray(actual)) return 'array';
    if (typeof actual === 'object' && actual !== null) return 'object';
    return 'string';
  }

  $: resolved = value !== undefined ? value : (schemaDef?.default);
  $: isExpr = Boolean(
    // Handle plain string variable references like "$color1"
    (typeof resolved === 'string' && resolved.startsWith('$')) ||
    // Handle expr object format { expr: "..." }
    (resolved && typeof resolved === 'object' && !Array.isArray(resolved) && 'expr' in (resolved as Record<string, unknown>) && (resolved as { expr?: unknown }).expr != null)
  );
  $: exprResolved = isExpr ? (typeof resolved === 'string' ? { expr: resolved.slice(1) } : resolved as { expr: string }) : null;
  $: type = isExpr ? 'expr' : resolveType(key, schemaDef, resolved);
  $: enumOpts = (schemaDef?.enum || schemaDef?.options || []) as unknown[];

  function sub(subKey: string, subVal: unknown) {
    const u: Record<string, unknown> = typeof resolved === 'object' && resolved !== null && !Array.isArray(resolved)
      ? { ...(resolved as Record<string, unknown>) }
      : {};
    u[subKey] = subVal;
    onChange(u);
  }

  function handleJson(e: Event) {
    const target = e.currentTarget as HTMLTextAreaElement;
    try { onChange(JSON.parse(target.value)); } catch(_) {}
  }

  function handleNum(e: Event) {
    const target = e.currentTarget as HTMLInputElement;
    const n = parseFloat(target.value);
    onChange(isNaN(n) ? target.value : n);
  }
</script>

{#if type === 'expr'}
  <div class="pf-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    <input class="pf-input pf-expr" type="text" value={exprResolved?.expr ?? ''}
      on:input={e => {
        const target = e.currentTarget as HTMLInputElement;
        // Store as plain string with $ prefix (variable reference)
        const val = target.value.trim();
        onChange(val.startsWith('$') ? val : (val ? '$' + val : ''));
      }}
      placeholder="$variableName" />
  </div>
{:else if type === 'color'}
  <div class="pf-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    <div class="pf-color-wrap">
      <input class="pf-input pf-color" type="color" value={valToHex(resolved)} on:change={e => onChange((e.currentTarget as HTMLInputElement).value)} />
      <span class="pf-color-label">{valToHex(resolved)}</span>
    </div>
  </div>
{:else if type === 'number'}
  <div class="pf-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    <input class="pf-input pf-num" type="text" inputmode="decimal"
      value={resolved !== undefined ? resolved : ''} on:input={handleNum} />
  </div>
{:else if type === 'boolean'}
  <div class="pf-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    <input class="pf-check" type="checkbox"
      checked={resolved !== undefined ? resolved : false}
      on:change={e => onChange((e.currentTarget as HTMLInputElement).checked)} />
  </div>
{:else if type === 'string'}
  <div class="pf-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    {#if enumOpts.length > 0}
      <select class="pf-input pf-select" on:change={e => onChange((e.currentTarget as HTMLSelectElement).value)}>
        {#each enumOpts as opt}
          <option value={opt} selected={(resolved ?? schemaDef?.default) === opt}>{opt}</option>
        {/each}
      </select>
    {:else}
      <input class="pf-input pf-str" type="text" value={resolved !== undefined ? resolved : ''}
        on:input={e => onChange((e.currentTarget as HTMLInputElement).value)} />
    {/if}
  </div>
{:else if type === 'object' && schemaDef?.properties}
  <details class="pf-obj" open={depth === 0}>
    <summary class="pf-obj-summary">{toReadableLabel(key)}</summary>
    <div class="pf-obj-body">
      {#each Object.entries(schemaDef.properties) as [sk, sd]}
        <svelte:self key={sk} schemaDef={sd} value={(resolved as Record<string, unknown> | undefined)?.[sk]} onChange={(v: unknown) => sub(sk, v)} depth={depth + 1} />
      {/each}
    </div>
  </details>
{:else}
  <div class="pf-row pf-json-row">
    <div class="pf-label-section">
      <div class="pf-lbl">{toReadableLabel(key)}</div>
    </div>
    <textarea class="pf-input pf-json" rows="2"
      value={JSON.stringify(resolved !== undefined ? resolved : (schemaDef?.default ?? null), null, 1)}
      on:change={handleJson}></textarea>
  </div>
{/if}

<style>
  .pf-row {
    display: grid;
    grid-template-columns: minmax(100px, 45%) 1fr;
    align-items: start;
    gap: 8px;
    min-height: 34px;
  }
  .pf-json-row { align-items: start; padding-top: 3px; }

  .pf-lbl {
    color: #666;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .pf-label-section {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .pf-input {
    border: 1px solid rgba(0,0,0,0.12);
    border-radius: 3px;
    background: rgba(255,255,255,0.8);
    color: #333;
    font-size: 14px;
    padding: 6px 8px;
    outline: none;
    min-width: 0;
    width: 100%;
    max-width: 180px;
    box-sizing: border-box;
    font-family: inherit;
  }
  .pf-input:focus { border-color: #667eea; }

  .pf-num { font-family: inherit; }
  .pf-str { color: #0000eb; font-family: inherit; }
  .pf-select { max-width: 180px; cursor: pointer; }
  .pf-json { font-family: inherit; font-size: 13px; resize: vertical; max-width: none; line-height: 1.4; }
  .pf-expr { font-family: inherit; background: #fffef5; color: #666; max-width: none; }

  .pf-color { width: 36px; height: 28px; padding: 1px 2px; cursor: pointer; flex: none; max-width: 36px; }
  .pf-color-wrap { display: flex; align-items: center; gap: 4px; }
  .pf-color-label { font-size: 13px; color: #555; font-family: inherit; }

  .pf-check { width: 16px; height: 16px; cursor: pointer; flex: none; }

  .pf-obj { margin: 2px 0; }
  .pf-obj-summary {
    cursor: pointer; list-style: none;
    font-size: 13px; font-weight: 600; color: #0000eb;
    padding: 2px 5px; background: rgba(0,0,235,0.05); border-radius: 3px;
    user-select: none;
  }
  .pf-obj-summary::-webkit-details-marker { display: none; }
  .pf-obj-body {
    display: flex; flex-direction: column; gap: 2px;
    padding: 3px 0 3px 8px;
    border-left: 2px solid rgba(0,0,235,0.1);
    margin-top: 2px;
  }
</style>
