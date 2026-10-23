import { describe, expect, it } from 'vitest';
import { escapeHtml, html, isSafeHtml, raw, SafeHtml } from './html.js';

describe('escapeHtml', () => {
  it('escapes the five HTML special characters', () => {
    expect(escapeHtml(`<a href="x">&'</a>`)).toBe('&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  });

  it('renders null, undefined and false as empty string', () => {
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml(undefined)).toBe('');
    expect(escapeHtml(false)).toBe('');
  });

  it('stringifies numbers and zero', () => {
    expect(escapeHtml(0)).toBe('0');
    expect(escapeHtml(12.5)).toBe('12.5');
  });
});

describe('html tagged template', () => {
  it('escapes interpolated user data by default', () => {
    const name = '<img src=x onerror=alert(1)>';
    const out = html`<span>${name}</span>`;
    expect(isSafeHtml(out)).toBe(true);
    expect(String(out)).toBe('<span>&lt;img src=x onerror=alert(1)&gt;</span>');
  });

  it('keeps static template text untouched', () => {
    expect(html`<b>ok</b>`.value).toBe('<b>ok</b>');
  });

  it('inserts nested SafeHtml without double escaping', () => {
    const inner = html`<i>${'<x>'}</i>`;
    expect(html`<p>${inner}</p>`.value).toBe('<p><i>&lt;x&gt;</i></p>');
  });

  it('joins arrays, escaping each plain item', () => {
    const items = ['<a>', html`<b>ok</b>`];
    expect(html`<ul>${items}</ul>`.value).toBe('<ul>&lt;a&gt;<b>ok</b></ul>');
  });

  it('does not escape attribute values passed through raw()', () => {
    const svg = raw('<svg><path d="M0"/></svg>');
    expect(html`<button>${svg}</button>`.value).toBe('<button><svg><path d="M0"/></svg></button>');
  });

  it('escapes attribute-breaking quotes in interpolated attribute values', () => {
    const v = '" onmouseover="alert(1)';
    expect(html`<div data-x="${v}"></div>`.value).toBe('<div data-x="&quot; onmouseover=&quot;alert(1)"></div>');
  });

  it('raw() treats null/undefined as empty and is recognized as safe', () => {
    expect(raw(null).value).toBe('');
    expect(raw('x')).toBeInstanceOf(SafeHtml);
    expect(isSafeHtml('<b>')).toBe(false);
  });
});
