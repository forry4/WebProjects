import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList, LobbyHero, LobbyUser, useListFade,
  readLobbyCache, writeLobbyCache, timeAgo,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import OrbitRules from "./rules.jsx";
import orbitCssText from "./Orbit.css?inline";


const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const ORBIT_WS = `${WS_BASE}/orbit/ws`;
const ORBIT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/orbit");
const styles = baseCss + lobbyCss + gameMenuCss + createModalCss
  + lobbyCreateRowCss + rulesModalCss + orbitCssText;

const PLANETS = ["mercury", "venus", "terra", "mars", "jupiter"];
const FACTIONS = ["robot", "human", "animod"];
const PLANET_GLYPH = { mercury: "☿", venus: "♀", terra: "⊕", mars: "♂", jupiter: "♃" };
const FACTION_GLYPH = { robot: "◇", human: "△", animod: "⬡" };
const BOARD_LETTER = {
  robot: { 1: "S", 2: "D" },
  human: { 1: "U", 2: "O" },
  animod: { 1: "N", 2: "P" },
};


function useSocket(onMessage) {
  const wsRef = useRef(null);
  const onMsg = useRef(onMessage);
  const [connected, setConnected] = useState(false);
  onMsg.current = onMessage;
  const connect = useCallback((url, firstMessage) => {
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => {
      setConnected(true);
      if (firstMessage) ws.send(JSON.stringify(firstMessage));
    };
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try { onMsg.current(JSON.parse(event.data)); } catch {}
    };
  }, []);
  const send = useCallback((message) => {
    try { wsRef.current?.send(JSON.stringify(message)); } catch {}
  }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null;
    setConnected(false);
  }, []);
  return { connected, connect, send, socketReady, disconnect };
}


function captureSummary(captured = []) {
  const counts = {};
  for (const planet of captured) counts[planet] = (counts[planet] || 0) + 1;
  return PLANETS.filter((planet) => counts[planet]).map((planet) => (
    <span className={`or-capture or-${planet}`} key={planet}>
      {PLANET_GLYPH[planet]}{counts[planet] > 1 ? `×${counts[planet]}` : ""}
    </span>
  ));
}


function PlayerRail({ player, name, active, me, leader }) {
  if (!player) return null;
  return <section className={`or-player${active ? " active" : ""}${me ? " mine" : ""}`}>
    <div className="or-player-name">
      <span>{name || "Player"}</span>
      {me && <em>you</em>}
      {leader?.owner === player.__pid && (
        <b className={`or-leader lv-${leader.level}`}>Leader {leader.level === 2 ? "gold" : "silver"}</b>
      )}
    </div>
    <div className="or-resources">
      <span><b>{player.credits}</b> Credits</span>
      <span><b>{player.zenithium}</b> Zenithium</span>
      <span><b>{player.hand?.length || 0}</b> cards</span>
    </div>
    <div className="or-captures" aria-label="Captured planets">
      {captureSummary(player.captured)}
      {!player.captured?.length && <small>no captured discs</small>}
    </div>
  </section>;
}


function Bonus({ token, catalog, compact = false }) {
  if (token == null) return <span className="or-bonus spent">spent</span>;
  const bonus = catalog?.bonuses?.[String(token)] || catalog?.bonuses?.[token];
  return <span className={`or-bonus${compact ? " compact" : ""}`} title={bonus?.description || "Bonus token"}>
    ✦ {compact ? token : (bonus?.description || `Bonus ${token}`)}
  </span>;
}


function InfluenceBoard({ game, myId, catalog }) {
  const mineIsPositive = game.order?.[0] === myId;
  const spaces = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
  return <section className="or-influence" aria-label="Planet influence board">
    <div className="or-track-key"><span>opponent control</span><b>Influence</b><span>your control</span></div>
    {PLANETS.map((planet) => {
      const raw = game.influence?.[planet];
      const position = raw == null ? null : (mineIsPositive ? raw : -raw);
      return <div className={`or-track or-${planet}`} key={planet}>
        <div className="or-track-name"><i>{PLANET_GLYPH[planet]}</i>{planet}</div>
        <div className="or-track-spaces">
          {spaces.map((space) => <span className={`or-space${Math.abs(space) === 4 ? " goal" : ""}`} key={space}>
            {position === space && <i className="or-disc" />}
          </span>)}
        </div>
        <Bonus token={game.planet_bonus?.[planet]} catalog={catalog} compact />
      </div>;
    })}
  </section>;
}


function TechBoard({ game, myId, otherId, catalog }) {
  const me = game.players?.[myId];
  const them = game.players?.[otherId];
  return <section className="or-tech" aria-label="Technology board">
    <header><h2>Technology</h2><span>Configuration {FACTIONS.map((f) => BOARD_LETTER[f][game.board_sides?.[f]]).join(".")}</span></header>
    <div className="or-tech-grid">
      {FACTIONS.map((faction) => <div className={`or-tech-col or-${faction}`} key={faction}>
        <h3><i>{FACTION_GLYPH[faction]}</i>{faction}</h3>
        <Bonus token={game.technology_bonus?.[faction]} catalog={catalog} compact />
        {[...(game.board?.[faction] || [])].reverse().map((space) => {
          const mine = (me?.technology?.[faction] || 0) === space.level;
          const theirs = (them?.technology?.[faction] || 0) === space.level;
          return <div className={`or-tech-space${mine ? " mine" : ""}${theirs ? " theirs" : ""}`} key={space.level}>
            <b>{space.level}</b><span>{space.description}</span>
            <i className="or-tech-pips">{mine ? "●" : ""}{theirs ? "○" : ""}</i>
          </div>;
        })}
      </div>)}
    </div>
    <p className="or-row-bonus">Complete all three tracks: level 1 → +1 influence · level 2 → +2 · level 3 → +3</p>
  </section>;
}


function AgentCard({ card, selected, onClick, hidden = false, small = false }) {
  if (hidden || card?.hidden) return <div className="or-agent hidden" aria-label="Hidden Agent"><span>ORBIT</span></div>;
  if (!card) return null;
  return <button type="button" className={`or-agent or-${card.planet} or-${card.faction}${selected ? " selected" : ""}${small ? " small" : ""}`}
    onClick={onClick} disabled={!onClick} title={card.description}>
    <span className="or-agent-top"><i>{PLANET_GLYPH[card.planet]}</i><b>{card.cost}</b><i>{FACTION_GLYPH[card.faction]}</i></span>
    <strong>{card.name}</strong>
    {!small && <span className="or-agent-text">{card.description}</span>}
    <span className="or-agent-foot">{card.planet} · {card.faction}</span>
  </button>;
}


function Columns({ game, pid, name, opponent = false }) {
  const player = game.players?.[pid];
  return <section className={`or-columns${opponent ? " opponent" : ""}`}>
    <h3>{name || "Player"}’s agents</h3>
    <div className="or-column-grid">
      {PLANETS.map((planet) => {
        const cards = player?.columns?.[planet] || [];
        const top = cards[cards.length - 1];
        return <div className={`or-column or-${planet}`} key={planet} title={top?.description || "Empty column"}>
          <span className="or-column-head">{PLANET_GLYPH[planet]} {planet}<b>{cards.length}</b></span>
          {top ? <AgentCard card={top} small /> : <span className="or-column-empty">empty</span>}
          {cards.length > 1 && <span className="or-stack">{cards.slice(0, -1).map((c) => c.name).join(" · ")}</span>}
        </div>;
      })}
    </div>
  </section>;
}


function choiceLabel(move, pending, game, catalog) {
  if ("planet" in move) return `${PLANET_GLYPH[move.planet] || ""} ${move.planet}`;
  if ("planets" in move) return move.planets.map((p) => `${PLANET_GLYPH[p]} ${p}`).join(" + ");
  if ("accept" in move) return move.accept ? "Do it" : "Skip";
  if ("faction" in move) return `${FACTION_GLYPH[move.faction]} ${move.faction}`;
  if ("tier" in move) return move.tier ? `Exile ${move.tier} cards` : "Skip";
  if ("cost" in move) return move.cost ? `Spend ${move.cost} → gain ${move.amount} influence` : "Skip";
  if ("card_id" in move) {
    const card = game.players && Object.values(game.players).flatMap((p) => p.hand || []).find((c) => c.id === move.card_id);
    return card?.name || `Card ${move.card_id}`;
  }
  if ("bonus_area" in move) {
    const board = move.bonus_area === "planet" ? game.planet_bonus : game.technology_bonus;
    const token = board?.[move.slot];
    const desc = catalog?.bonuses?.[String(token)]?.description;
    return `${move.slot}: ${desc || `bonus ${token}`}`;
  }
  if ("branch" in move) return pending?.branch_labels?.[move.branch] || `Option ${move.branch + 1}`;
  return "Choose";
}


function DecisionPanel({ game, catalog, sendMove }) {
  const pending = game.pending?.task;
  const moves = game.legal_moves || [];
  if (!pending || !moves.length) return null;
  const title = pending.label || game.pending?.source || "Resolve effect";
  return <section className="or-decision" aria-live="polite">
    <span className="or-eyebrow">Decision required</span>
    <h2>{title}</h2>
    <div className="or-choice-grid">
      {moves.map((move, index) => <button type="button" key={index} onClick={() => sendMove(move)}>
        {choiceLabel(move, pending, game, catalog)}
      </button>)}
    </div>
  </section>;
}


function Lobby({ authUser, myId, onExit, openGames, myGames, history, historyShown,
  historyMore, refreshing, fetchGames, joinGame, resumeGame, cancelGame,
  showCreate, setShowCreate, createOpp, setCreateOpp, createSetup, setCreateSetup,
  createGame, lobbyTab, setLobbyTab, showRules, setShowRules, toast }) {
  const active = notWaiting(myGames);
  return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}>
    <style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="orbit">
        <LobbyCreateRow createLabel="+ Create Orbit" onCreate={() => setShowCreate(true)}
          onJoin={joinGame} onRefresh={fetchGames} refreshing={refreshing}
          onRules={() => setShowRules(true)} />
      </LobbyHero>
      <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
        { key: "open", label: "Open", count: openGames.length || null },
        { key: "active", label: "Active", count: active.length || null },
        { key: "history", label: "History", count: history.length || null },
      ]} />
      <div className={`or-lobby-cols lby-cols tab-${lobbyTab}`}>
        <div className="lby-col-open">
          <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><div className="lby-card-title">{g.host_id === myId ? "Your game" : `${g.host_name || "Player"}’s game`}<span className="lby-seats">1/2</span></div>
              <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div></div>
            <div className="lby-card-actions">{g.host_id === myId ? <>
              <LobbyAction kind="secondary" onClick={() => resumeGame(g.id)}>Return</LobbyAction>
              <LobbyAction kind="danger" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
            </> : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}</div>
          </div>)}</div>
        </div>
        <div className="lby-col-active">
          <LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><div className="lby-card-title">{(g.you_are_p1 ? g.player2_name : g.player1_name) || "Opponent"}</div>
              <div className="lby-card-meta">{g.turn ? `turn ${g.turn} · ` : ""}{timeAgo(g.updated_at)}</div></div>
            <div className="lby-card-actions"><TurnBadge mine={g.your_turn}>{g.your_turn ? "Your turn" : "Their turn"}</TurnBadge>
              <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction></div>
          </div>)}</div>
        </div>
        <div className="lby-col-history">
          <LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser ? "No finished games yet." : "Log in to keep your game history."}</LobbyEmpty>}
          <div className="lby-list">{historyShown.map((g) => <div className="lby-card lby-card-hist" key={g.id}>
            <div className="lby-card-info"><div className="lby-card-title"><span className={`hist-result ${g.outcome}`}>{g.outcome === "won" ? "Won" : g.outcome === "draw" ? "Draw" : "Lost"}</span>
              <span className="hist-scores"> vs {g.you_are_p1 ? g.player2_name : g.player1_name}</span></div>
              <div className="lby-card-meta">{g.turns ? `${g.turns} turns · ` : ""}{timeAgo(g.updated_at)}</div></div>
          </div>)}{historyMore}</div>
        </div>
      </div>
    </div></div>
    {showCreate && <CreateModal title="New Orbit game" onClose={() => setShowCreate(false)}>
      <CmRow label="Opponent"><CmSeg value={createOpp} onChange={setCreateOpp} options={[
        { value: "friend", label: "VS Friend" }, { value: "ai", label: "VS Random AI" },
      ]} /></CmRow>
      <CmRow label="Technology board"><CmSeg value={createSetup} onChange={setCreateSetup} options={[
        { value: "sun", label: "S.U.N.", title: "The recommended first-game board" },
        { value: "random", label: "Random", title: "Flip all three faction strips independently" },
      ]} /></CmRow>
      <span className="cm-hint">Complete 1v1 rules and all 90 base-game Agents. The first AI deliberately chooses random legal moves.</span>
      <div className="cm-footer"><span className="cm-summary">Creating: <b>{createOpp === "ai" ? "vs Random AI" : "vs Friend"}</b></span>
        <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai", createSetup)}>Create Game</button></div>
    </CreateModal>}
    {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
    {toast && <div className="or-toast">{toast}</div>}
  </div>;
}


export default function Orbit({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [toast, setToast] = useState("");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("orbit", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("orbit", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("orbit", myId, "history", []));
  const [refreshing, setRefreshing] = useState(false);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createSetup, setCreateSetup] = useState("sun");
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [selectedCard, setSelectedCard] = useState(null);
  const [mulligan, setMulligan] = useState([]);
  const urlAttempt = useRef(null);
  const [historyShown, historyMore] = useProgressiveList(history);
  useListFade();

  const handleMessage = useCallback((message) => {
    setConnecting(false);
    if (message.type === "error") {
      if (urlAttempt.current) {
        const attempted = urlAttempt.current;
        urlAttempt.current = null;
        try {
          if (localStorage.getItem("orbit_roomId") === attempted) localStorage.removeItem("orbit_roomId");
          localStorage.removeItem(`orbit_token_${attempted}_${myId}`);
        } catch {}
        setRoomData(null); setRoomId(""); setScreen("lobby");
        replacePath(buildPath("orbit"));
      }
      setToast(message.message || "Something went wrong");
      return;
    }
    const room = message.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const token = room.reconnect_tokens?.[myId];
    if (token) {
      try {
        localStorage.setItem(`orbit_token_${rid}_${myId}`, token);
        localStorage.setItem("orbit_roomId", rid);
      } catch {}
    }
    setRoomData(room); setRoomId(rid);
    const inGame = room.status === "playing" || room.status === "over";
    if (message.type === "created" || message.type === "joined") {
      if (rid) pushPath(buildPath("orbit", rid));
      urlAttempt.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (inGame) setScreen("game");
  }, [myId, roomId]);

  const { connected, connect, send, socketReady, disconnect } = useSocket(handleMessage);
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);

  useEffect(() => {
    try {
      const cached = localStorage.getItem("orbit_catalog");
      if (cached) setCatalog(JSON.parse(cached));
    } catch {}
    fetch(`${ORBIT_HTTP}/catalog`).then((r) => r.json()).then((data) => {
      if (!data.cards) return;
      setCatalog(data);
      try { localStorage.setItem("orbit_catalog", JSON.stringify(data)); } catch {}
    }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setRefreshing(true);
    fetch(`${ORBIT_HTTP}/games`).then((r) => r.json()).then((data) => {
      const rows = data.games || []; setOpenGames(rows); writeLobbyCache("orbit", myId, "open", rows);
    }).catch(() => {}).finally(() => setRefreshing(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${ORBIT_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((data) => {
        const rows = data.games || []; setMyGames(rows); writeLobbyCache("orbit", myId, "mine", rows);
      }).catch(() => {});
      fetch(`${ORBIT_HTTP}/games/history`, { headers }).then((r) => r.json()).then((data) => {
        const rows = data.games || []; setHistory(rows); writeLobbyCache("orbit", myId, "history", rows);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  const createGame = useCallback((vsAi, configuration) => {
    const rid = Math.random().toString(36).slice(2, 7).toUpperCase();
    setConnecting(true); setRoomId(rid); setShowCreate(false);
    connect(`${ORBIT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi, configuration,
    });
  }, [connect, myId, authUser]);

  const joinGame = useCallback((raw) => {
    const rid = String(raw || "").trim().toUpperCase();
    if (!rid) return;
    setConnecting(true); setRoomId(rid);
    connect(`${ORBIT_WS}/${rid}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  }, [connect, myId, authUser]);

  const resumeGame = useCallback((rid) => {
    let token = null;
    try { token = localStorage.getItem(`orbit_token_${rid}_${myId}`); } catch {}
    setConnecting(true); setRoomId(rid);
    connect(`${ORBIT_WS}/${rid}/${myId}`, token
      ? { action: "reconnect", token }
      : { action: "join", name: authUser?.name || "Player", session_token: authUser?.session_token || null });
  }, [connect, myId, authUser]);

  const cancelGame = useCallback((gid) => {
    if (!authUser?.session_token) return;
    fetch(`${ORBIT_HTTP}/games/${gid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(fetchGames).catch(() => {});
  }, [authUser, fetchGames]);

  const reconnectNow = useCallback(() => {
    let token = null;
    try { token = localStorage.getItem(`orbit_token_${roomId}_${myId}`); } catch {}
    if (token) connect(`${ORBIT_WS}/${roomId}/${myId}`, { action: "reconnect", token });
  }, [roomId, myId, connect]);
  useAutoReconnect({
    enabled: !!roomId && screen === "game" && roomData?.status !== "over",
    connected, connect: reconnectNow, socketReady,
  });

  const leaveToLobby = useCallback(() => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    replacePath(buildPath("orbit"));
  }, [disconnect]);

  useEffect(() => {
    const match = /\/orbit\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    if (match) {
      const rid = match[1].toUpperCase(); urlAttempt.current = rid; resumeGame(rid);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => subscribe((route) => {
    if (route.game !== "orbit") return;
    if (route.room) { urlAttempt.current = route.room; resumeGame(route.room); }
    else leaveToLobby();
  }), [resumeGame, leaveToLobby]);

  const game = roomData?.game;
  const names = roomData?.players || {};
  const otherId = game?.order?.find((pid) => pid !== myId);
  const me = game?.players?.[myId];
  const other = game?.players?.[otherId];
  const legal = game?.legal_moves || [];
  const isMyTurn = legal.length > 0;
  const over = game?.phase === "over";

  useEffect(() => {
    if (!me?.hand?.some((card) => card.id === selectedCard)) setSelectedCard(null);
  }, [me?.hand, selectedCard]);
  useEffect(() => { if (game?.phase !== "mulligan") setMulligan([]); }, [game?.phase]);

  if (connecting && screen === "lobby") return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
  if (screen === "lobby") return <Lobby {...{
    authUser, myId, onExit, openGames, myGames, history, historyShown, historyMore,
    refreshing, fetchGames, joinGame, resumeGame, cancelGame, showCreate, setShowCreate,
    createOpp, setCreateOpp, createSetup, setCreateSetup, createGame, lobbyTab, setLobbyTab,
    showRules, setShowRules, toast,
  }} />;

  if (screen === "waiting") {
    const host = roomData?.host === myId;
    return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style>
      <div className="or-wait"><span className="or-kicker">Orbit · 1 vs 1</span><h1>Room {roomId}</h1>
        <p>{Object.keys(names).length < 2 ? "Waiting for an opponent…" : "Both players are here."}</p>
        <div className="or-wait-seats">{Object.values(names).map((name) => <span key={name}>{name}</span>)}</div>
        {host && Object.keys(names).length >= 2 && <button type="button" className="or-primary" onClick={() => send({ action: "start" })}>Start game</button>}
        <LobbyAction kind="secondary" onClick={leaveToLobby}>Back to lobby</LobbyAction>
      </div>{toast && <div className="or-toast">{toast}</div>}
    </div>;
  }

  if (!game || !me) return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style><LobbyLoading label="Loading Orbit…" /></div>;

  const cardMoves = selectedCard == null ? [] : legal.filter((move) => move.card_id === selectedCard);
  const selectedAgent = me.hand.find((card) => card.id === selectedCard);
  const recruitCost = selectedAgent
    ? Math.max(0, selectedAgent.cost - (me.columns?.[selectedAgent.planet]?.length || 0))
    : null;
  const technologyCost = selectedAgent
    ? (me.technology?.[selectedAgent.faction] || 0) + 1
    : null;
  const winnerName = game.winner ? names[game.winner] : null;
  return <div className="app orbit or-game" style={{ "--lby-accent": GAME_ACCENTS.orbit }}>
    <style>{styles}</style>
    <LobbyHeader title={`Orbit · ${roomId}`} user={<span className={`or-connection${connected ? "" : " lost"}`}>{connected ? (authUser?.name || "Connected") : "Reconnecting…"}</span>}
      menu={<GameMenu items={[
        { label: "How to play", onClick: () => setShowRules(true), icon: "?" },
        { label: "Return to lobby", onClick: leaveToLobby, icon: "←" },
        !over && { label: "Abandon game", onClick: () => setConfirmAbandon(true), icon: "×", danger: true },
      ]} />} />
    <main className="or-table">
      <div className="or-score-rail">
        <PlayerRail player={{ ...other, __pid: otherId }} name={names[otherId]} active={!over && game.turn_pid === otherId} leader={game.leader} />
        <PlayerRail player={{ ...me, __pid: myId }} name={names[myId]} active={!over && game.turn_pid === myId} me leader={game.leader} />
      </div>

      {over && <section className="or-result">
        <span>{game.winner === myId ? "Victory" : game.winner ? "Game over" : "Draw"}</span>
        <h1>{winnerName ? `${winnerName} controls the senate` : "The Agent supply was exhausted"}</h1>
        <button type="button" onClick={leaveToLobby}>Return to lobby</button>
      </section>}

      {game.phase === "mulligan" && isMyTurn && <section className="or-mulligan">
        <span className="or-eyebrow">Opening hand</span><h2>Replace any Agents?</h2>
        <p>Select any cards you want to discard, then confirm. You draw back to four.</p>
        <div className="or-hand">{me.hand.map((card) => <AgentCard card={card} key={card.id} selected={mulligan.includes(card.id)}
          onClick={() => setMulligan((old) => old.includes(card.id) ? old.filter((id) => id !== card.id) : [...old, card.id])} />)}</div>
        <button type="button" className="or-primary" onClick={() => sendMove({ action: "mulligan", card_ids: [...mulligan].sort((a, b) => a - b) })}>
          {mulligan.length ? `Replace ${mulligan.length} card${mulligan.length === 1 ? "" : "s"}` : "Keep this hand"}
        </button>
      </section>}
      {game.phase === "mulligan" && !isMyTurn && <section className="or-status"><span className="or-spinner" /> Waiting for the other mulligan…</section>}

      {game.phase !== "mulligan" && <>
        <InfluenceBoard game={game} myId={myId} catalog={catalog} />
        <div className="or-sideboards"><TechBoard game={game} myId={myId} otherId={otherId} catalog={catalog} />
          <section className="or-log"><h2>Chronicle</h2><div>{(game.log || []).slice(-14).map((entry, i) => <p key={`${entry.turn}-${i}`}><b>{entry.turn}</b>{entry.message}</p>)}</div></section>
        </div>
        <Columns game={game} pid={otherId} name={names[otherId]} opponent />
        <Columns game={game} pid={myId} name={names[myId]} />

        {!over && game.pending && game.pending_pid === myId && <DecisionPanel game={game} catalog={catalog} sendMove={sendMove} />}
        {!over && game.pending && game.pending_pid !== myId && <section className="or-status"><span className="or-spinner" /> {names[game.pending_pid] || "Opponent"} is resolving {game.pending.source}…</section>}
        {!over && !game.pending && !isMyTurn && <section className="or-status"><span className="or-spinner" /> {names[game.turn_pid] || "Opponent"} is choosing an action…</section>}

        <section className="or-hand-zone">
          <div className="or-hand-head"><div><span className="or-eyebrow">Your hand</span><h2>{isMyTurn && !game.pending ? "Choose an Agent" : "Agents in reserve"}</h2></div>
            <span>{me.hand.length} / {game.leader?.owner === myId ? (game.leader.level === 2 ? 6 : 5) : 4}</span></div>
          <div className="or-hand">{me.hand.map((card) => <AgentCard card={card} key={card.id} selected={selectedCard === card.id}
            onClick={isMyTurn && !game.pending ? () => setSelectedCard(card.id) : null} />)}</div>
          {selectedCard != null && isMyTurn && !game.pending && <div className="or-action-bar">
            <span>Play <b>{me.hand.find((card) => card.id === selectedCard)?.name}</b> as:</span>
            <div>{["recruit", "technology", "leader"].map((action) => {
              const move = cardMoves.find((candidate) => candidate.action === action);
              const label = action === "recruit"
                ? `Recruit · ${recruitCost} Credits`
                : action === "technology"
                  ? `Develop ${selectedAgent?.faction || "Technology"} · ${technologyCost} Zenithium`
                  : `Become Leader · ${selectedAgent?.faction || "Faction"}`;
              return <button type="button" key={action} disabled={!move} onClick={() => move && sendMove(move)}>{label}</button>;
            })}</div>
          </div>}
        </section>
      </>}
    </main>
    {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
    {confirmAbandon && <div className="or-confirm" onClick={() => setConfirmAbandon(false)}><div role="dialog" onClick={(e) => e.stopPropagation()}>
      <h2>Abandon this game?</h2><p>Your opponent will win immediately.</p><span><button type="button" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
        <button type="button" className="danger" onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>Abandon</button></span>
    </div></div>}
    {toast && <div className="or-toast">{toast}</div>}
  </div>;
}
