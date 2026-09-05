/*
 * Zenith puts its effects in a small, repeatable icon vocabulary.  Orbit's
 * imported card payload intentionally keeps the source's readable sentence,
 * so this display-only adapter turns that sentence into the same at-a-glance
 * summary.  The sentence remains the authority for the complete effect and is
 * always available in the card modal.
 */
import React from "react";

export const EFFECT_SYMBOLS = {
  credits: { glyph: "◉", label: "Credits" },
  zenithium: { glyph: "✦", label: "Zenithium" },
  influence: { glyph: "◌", label: "Influence" },
  mobilize: { glyph: "⇣", label: "Mobilize an Agent" },
  exile: { glyph: "⊘", label: "Exile an Agent" },
  transfer: { glyph: "⇄", label: "Transfer an Agent" },
  develop: { glyph: "⌁", label: "Develop technology" },
  leader: { glyph: "♛", label: "Take or improve the Leader badge" },
  bonus: { glyph: "✪", label: "Draw or claim a bonus token" },
  discard: { glyph: "⌫", label: "Discard from your hand" },
  special: { glyph: "◆", label: "A conditional or choice effect" },
};

function amountFor(text, pattern) {
  const match = text.match(pattern);
  return match ? match[1] : null;
}

export function cardSymbols(card) {
  const text = card?.description || "";
  const symbols = [];
  const add = (key, amount = null) => symbols.push({ key, amount, ...EFFECT_SYMBOLS[key] });
  const credits = amountFor(text, /(?:Gain|give) (\d+) Credits/i);
  const zenithium = amountFor(text, /(?:Gain|give) (\d+) Zenithium/i);
  const influence = amountFor(text, /(?:Gain|mobilize) (\d+) influence/i);
  if (credits) add("credits", credits);
  if (zenithium) add("zenithium", zenithium);
  if (influence) add("influence", influence);
  if (/\bMobilize\b/i.test(text)) add("mobilize", amountFor(text, /Mobilize (\d+)/i));
  if (/\bExile\b/i.test(text)) add("exile", amountFor(text, /Exile (\d+)/i));
  if (/\bTransfer\b/i.test(text)) add("transfer", amountFor(text, /Transfer (\d+)/i));
  if (/\bDevelop\b/i.test(text)) add("develop");
  if (/\bLeader\b/i.test(text)) add("leader");
  if (/\bbonus\b/i.test(text)) add("bonus");
  if (/\bDiscard\b/i.test(text)) add("discard", amountFor(text, /Discard (\d+)/i));
  if (/\b(can|choose|per |if |for each|respectively|of your choice)\b/i.test(text)) add("special");
  return symbols.length ? symbols : [{ key: "special", ...EFFECT_SYMBOLS.special }];
}

export function CardSymbols({ card, className = "" }) {
  return <span className={`or-card-symbols${className ? ` ${className}` : ""}`} aria-label="Card effects">
    {cardSymbols(card).map((symbol, index) => <span className="or-card-symbol" key={`${symbol.key}-${index}`}
      title={`${symbol.amount ? `${symbol.amount} ` : ""}${symbol.label}`}>
      <i aria-hidden="true">{symbol.glyph}</i>{symbol.amount && <b>{symbol.amount}</b>}
      <span className="or-sr-only">{`${symbol.amount ? `${symbol.amount} ` : ""}${symbol.label}`}</span>
    </span>)}
  </span>;
}

export function SymbolLegend({ card = null, compact = false }) {
  const symbols = card ? cardSymbols(card) : Object.entries(EFFECT_SYMBOLS)
    .map(([key, symbol]) => ({ key, ...symbol }));
  const unique = symbols.filter((symbol, index) => symbols.findIndex((item) => item.key === symbol.key) === index);
  return <div className={`or-symbol-legend${compact ? " compact" : ""}`} aria-label="Card symbol legend">
    <span className="or-symbol-legend-title">Card symbol legend</span>
    {unique.map((symbol) => <span key={symbol.key}>
      <i aria-hidden="true">{symbol.glyph}</i><b>{symbol.label}</b>
    </span>)}
  </div>;
}
