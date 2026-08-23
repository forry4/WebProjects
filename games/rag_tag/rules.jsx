import { RulesSection, RulesFacts, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

/* The WORDS for the shared RulesModal. Chrome (the panel, the scroller, the
   close button) lives in shared/lobby.jsx; only this file is game-specific. */

export default function RagTagRules() {
  return (
    <>
      <RulesSection title="The idea">
        <p>
          You and your opponent each field a team of two Fighters. Every round you
          both flip the top card of your Fight Deck at the same time and both cards
          resolve at once — you cannot react, only prepare. Then you add one card to
          your deck, anywhere you like, <b>without reordering what is already there</b>.
          Your deck is never shuffled, so you always know what is coming. So does your
          opponent, eventually.
        </p>
      </RulesSection>

      <RulesSection title="Setup">
        <RulesFacts items={[
          "You are dealt 6 of the 12 Fighters. Pick 1, pass the rest, pick a second from theirs.",
          "Each Fighter's Starting Card is set aside — those two, in an order you choose, are your whole Fight Deck.",
          "Their other 18 cards shuffle together into your Build Deck.",
        ]} />
      </RulesSection>

      <RulesSection title="A round">
        <RulesDefs items={[
          ["FIGHT!", "Both players flip one card at a time and resolve them simultaneously, until both Fight Decks run out."],
          ["BUILD!", "Draw the top 3 of your Build Deck, secretly keep 1 and slide it anywhere into your Fight Deck. The other 2 go to the bottom."],
        ]} />
        <p>
          The cards you just played keep their order and become next round's Fight
          Deck — one card longer than last time.
        </p>
      </RulesSection>

      <RulesSection title="Actions">
        <RulesDefs items={[
          ["Active Fighter", "Whoever's card came up. They perform the actions, and they are the default target."],
          ["Attack", "The target loses HP equal to your Power at the START of the turn. Power gained this turn does not count."],
          ["Block", "Negates every Attack from the opposing team this turn — but not Direct Damage. If it caught at least one Attack, even a 0-Power one, its Bonus Action fires."],
          ["Direct Damage", "Unblockable HP loss. Still stopped by a STOP, still triggers health-track icons."],
          ["Heal", "Move up. If you are hit on the same turn, only the difference moves."],
          ["Cancel", "The opposing card is ignored entirely."],
          ["Success", "An Attack nobody Blocked, or a Block that caught something. Some cards pay a bonus for it."],
        ]} />
      </RulesSection>

      <RulesSection title="Health tracks">
        <RulesFacts items={[
          "Icons fire when your marker LANDS ON or PASSES THROUGH them — after every marker has finished moving.",
          "A STOP halts the marker the instant it lands there, going up or down.",
          "Sitting on an icon and stepping off it pays nothing.",
        ]} />
      </RulesSection>

      <RulesSection title="Winning">
        <RulesFacts items={[
          "A Fighter on KO at the end of a turn loses the fight for their team.",
          "Both teams down in the same turn is a draw.",
          "If you cannot draw 3 cards to Build, the fight is a draw — which caps a game at about sixteen rounds.",
        ]} />
        <RulesTip>
          Where you slide a card matters more than which card it is. Line your Block
          up against the Attack you know is coming, and your Attack against the gap.
        </RulesTip>
      </RulesSection>

      <RulesSection title="Fighters">
        <p>
          All twelve have their own board, health track and ten-card deck, and several
          break the rules above on purpose — Maman Brijit comes back from the dead,
          Bödvar turns into a bear, the Wild Bunch can only ever move one space a turn,
          and the Fey Folk are three characters taking turns to die. Their boards say
          what they do; the golden rule is that a card or a board always beats the
          rulebook.
        </p>
      </RulesSection>
    </>
  );
}
