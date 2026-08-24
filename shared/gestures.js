/* Cross-game input gestures.
 *
 * `useCardInfoGesture` was written for Dontminion and is now used by Rag Tag
 * too. It lives here rather than being copied because the tricky half is not the
 * gesture, it is the PLATFORM DIFFERENCES below — and a second copy of that is a
 * second thing to get wrong when a browser changes its mind.
 */
import { useRef, useCallback, useEffect } from "react";

const LONG_PRESS_MS = 450;
const LONG_PRESS_SLOP = 10;      // finger drift still counted as a hold, not a scroll

/* Right-click (desktop) / press-and-hold (touch) opens a detail view, WHATEVER
 * the plain click is wired to do — the card you can play or pick is exactly the
 * one you most want to read first, and its click is already taken.
 *
 * Android fires `contextmenu` on a long press, but iOS Safari does not (it runs
 * its own selection callout instead), so touch gets a real timer rather than
 * relying on the event. Both paths funnel through one `fired` flag: whichever
 * wins, the other is a no-op and the tap that follows is swallowed, so holding a
 * card can never also play it.
 *
 * Spread the result onto the element:  <div {...useCardInfoGesture(open)} />
 * Passing no handler returns {}, so a read-only face costs nothing.
 */
export function useCardInfoGesture(onInfo) {
  const timer = useRef(null);
  const fired = useRef(false);
  const from = useRef(null);
  const clear = useCallback(() => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
  }, []);
  useEffect(() => clear, [clear]);          // never leave a timer behind on unmount
  if (!onInfo) return {};
  const open = () => { clear(); fired.current = true; onInfo(); };
  return {
    onContextMenu: (e) => {
      e.preventDefault(); e.stopPropagation();   // no browser menu on a card
      if (!fired.current) open();
    },
    onPointerDown: (e) => {
      fired.current = false;                     // a fresh press re-arms the click
      if (e.pointerType === "mouse") return;     // right-click already covers a mouse
      from.current = { x: e.clientX, y: e.clientY };
      clear();
      timer.current = setTimeout(open, LONG_PRESS_MS);
    },
    onPointerMove: (e) => {
      if (!timer.current || !from.current) return;
      if (Math.abs(e.clientX - from.current.x) > LONG_PRESS_SLOP
        || Math.abs(e.clientY - from.current.y) > LONG_PRESS_SLOP) clear();   // they're scrolling
    },
    onPointerUp: clear,
    onPointerCancel: clear,
    onPointerLeave: clear,
    onClickCapture: (e) => {
      // the hold already answered — don't let the release ALSO play the card
      if (fired.current) { e.preventDefault(); e.stopPropagation(); fired.current = false; }
    },
  };
}
