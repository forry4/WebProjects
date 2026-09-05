import { RulesDefs, RulesFacts, RulesSection, RulesTip } from "../../shared/lobby.jsx";
import { SymbolLegend } from "./symbols.jsx";

export default function OrbitRules() {
  return <>
    <RulesFacts items={[
      { k: "Players", v: "2" },
      { k: "Time", v: "about 30 min" },
      { k: "Goal", v: "control the solar system" },
    ]} />

    <RulesSection title="Win immediately">
      <p>Capture influence discs in any one of three ways:</p>
      <RulesDefs items={[
        { t: "Absolute", d: "3 discs from the same planet." },
        { t: "Democratic", d: "4 discs from four different planets." },
        { t: "Popular", d: "5 discs in any combination." },
      ]} />
    </RulesSection>

    <RulesSection title="Setup">
      <p>Each player starts with 12 Credits, 1 Zenithium, and 4 secret Agent cards.
        The second player begins with 1 Terra influence. Before the first turn, each
        player may replace any number of starting cards.</p>
      <p>Eight random bonus tokens begin face up: one on each planet and one on each
        technology track. The S.U.N. board is the recommended first-game setup;
        Random flips each of its three faction strips independently.</p>
    </RulesSection>

    <RulesSection title="One card, one action">
      <RulesDefs items={[
        { t: "Recruit", d: "Put the Agent in its planet column, pay its cost minus the cards already there, gain 1 matching influence, then resolve its text left to right." },
        { t: "Develop", d: "Discard the Agent, pay the next technology level in Zenithium (1–5), advance its faction, then resolve that level and every lower level from top to bottom." },
        { t: "Become Leader", d: "Discard the Agent. Robot takes the badge and gains 1 Zenithium; Human takes it and gains 3 Credits; Animod takes it and mobilizes 2." },
      ]} />
      <RulesTip>A recruited Agent reduces the future cost of its column, and it is
        already the top card when its own effects resolve.</RulesTip>
    </RulesSection>

    <RulesSection title="Card symbols">
      <p>Agent faces use the same compact effect symbols as Zenith. The coloured
        outline identifies its planet, the top-left number is its Credit cost,
        and the top-right shape identifies its faction. Open a card to read its
        complete effect and the legend for the symbols on that card.</p>
      <SymbolLegend />
      <RulesTip>Some effects have conditions, choices, targets, or a sequence.
        The ◆ symbol is the reminder to open the card: its detail panel always
        gives the complete instruction.</RulesTip>
    </RulesSection>

    <RulesSection title="Influence and planets">
      <p>Influence moves a planet disc one space toward you. Reaching your control
        zone captures it; extra movement is lost. The first capture from a planet
        also resolves and removes its face-up bonus. A fresh disc appears in the
        middle only at the end of the active player’s turn.</p>
      <p>An effect can move a disc toward your opponent—even far enough for them to
        capture it and win during your turn.</p>
    </RulesSection>

    <RulesSection title="Technology bonuses">
      <p>The first player to reach level 2 on a faction resolves that track’s bonus
        after its level-2 effect and before level 1. Completing all three tracks at
        level 1, 2, or 3 grants respectively 1, 2, or 3 influence on one planet,
        after all track effects.</p>
    </RulesSection>

    <RulesSection title="Agent effects">
      <RulesDefs items={[
        { t: "Mobilize", d: "Draw the top Agent and add it to its matching column without resolving its text or its normal recruit influence." },
        { t: "Exile", d: "Discard the most recently added Agent from the chosen column." },
        { t: "Transfer", d: "Move the opponent’s top Agent to your matching column without resolving it." },
        { t: "Leader badge", d: "Taking it from elsewhere gives the silver side and a hand limit of 5. Taking your own silver badge upgrades it to gold and a limit of 6." },
      ]} />
    </RulesSection>

    <RulesSection title="End of turn">
      <p>Draw up to 4 cards, or 5/6 while holding the silver/gold Leader. Never
        discard down if an effect put you above the limit. Then return every planet
        disc captured this turn to its middle space and pass play.</p>
      <p>If the Agent deck or face-down bonus reserve runs out, shuffle its discard
        pile to make a new one.</p>
    </RulesSection>
  </>;
}
