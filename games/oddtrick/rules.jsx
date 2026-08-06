// Oddtrick's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Oddtrick's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function OddtrickRules() {
	return (
		<>
			<p className="rl-lead">
				A two-player card game in the trick-taking family — but with the usual assumption
				turned off. Winning tricks is <b>not simply good</b>. The <b>even-numbered</b> tricks
				pay <b>+2</b> to whoever wins them; the <b>odd-numbered</b> ones cost <b>1</b>. Six
				good tricks against seven bad ones, so the two players' trick scores always add up to
				exactly <b>+5</b>. Sweeping all thirteen tricks scores 5; taking exactly the six even
				ones scores 12. The game is about <i>which</i> tricks you win.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "2 (friend or bot)" },
				{ k: "Length", v: "10–15 minutes for a round" },
				{ k: "You win by", v: "Scoring more than your opponent on the contract" },
			]} />

			<RulesSection title="If you've never played a trick-taking game">
				<p>
					Players take turns putting one card each into the middle — that's a <b>trick</b>.
					The player who plays the higher card by the rules below <b>wins</b> the trick and
					leads the next one. A <b>trump</b> suit, if there is one, beats every other suit.
					"Following suit" means playing the same suit that was led, and here it is
					<b> compulsory</b> when you can.
				</p>
			</RulesSection>

			<RulesSection title="The deal">
				<p>
					The deck is 32 cards: <b>7, 8, 9, 10, J, Q, K, A</b> in four suits. You each get
					thirteen cards, laid out in an unusual way:
				</p>
				<ul>
					<li><b>7 cards in hand</b>, as normal — yours alone.</li>
					<li><b>Three piles of 2.</b> Only a pile's <b>top</b> card can be played. When the
						top is gone, the card underneath becomes playable — and <b>visible to both
						players</b> from that moment.</li>
					<li>The <b>middle pile's bottom card is face-up from the start</b>, so you both know
						one card that's coming. The outer two piles' bottom cards are hidden from
						everyone — <b>including their owner</b>.</li>
					<li><b>Six cards sit out</b> of the deal entirely, unseen, and are revealed at the
						end. Nobody has them — and any card you can't account for might be among
						them rather than in your opponent's hand.</li>
				</ul>
			</RulesSection>

			<RulesSection title="The auction">
				<p>
					Before playing, you bid for the contract. A bid is a <b>number (1–12)</b> and a
					<b> denomination</b> — one of the four suits, or <b>no-trump</b>. The number is a
					promise: <i>I will finish with at least this many trick points.</i>
				</p>
				<RulesDefs items={[
					{ t: "The opener must bid", d: "Passing is not allowed on the first bid, however bad the hand is." },
					{ t: "Denominations are ranked", d: "♣ < ♦ < ♥ < ♠ < NT. A bid at the same number in a higher-ranked denomination outranks the one standing." },
					{ t: "Overtaking", d: "Match the number in a higher-ranked denomination, or raise it by 1 or 2 — no bigger jumps — in any denomination YOU have not named before. Or pass." },
					{ t: "The last bid wins", d: "That player is the declarer, their denomination is trump (or no-trump), and their number is the target." },
					{ t: "Declarer leads", d: "The declarer leads to trick 1 — which is an odd, LOSING trick. Leading first is a real disadvantage, and it's why the auction isn't a free-for-all." },
				]} />
			</RulesSection>

			<RulesSection title="The talon">
				<p>
					After the auction, the declarer is shown <b>three</b> of the six set-aside cards
					and may take <b>one</b> into hand, discarding a hand card face-down in its place
					(pile cards can't be swapped). The defender is told <i>that</i> a swap happened —
					never which cards. Winning the auction buys information as well as the contract.
				</p>
			</RulesSection>

			<RulesSection title="Null — the contract for a hopeless hand">
				<p>
					Instead of a number, you may bid <b>Null</b>: a promise to win <b>no +2 trick</b>
					for the whole round. It slots into the ladder as a 6 (above no-trump 6, below 7)
					and is played without trump. Make it and you score a flat <b>12</b>; if even one
					scoring trick lands on you, your opponent scores <b>10</b> instead.
				</p>
				<p>
					Winning a −1 trick is legal — but it puts you <b>on lead into the +2 trick that
					follows</b>, the one seat you can't duck from. The odd tricks are not free.
				</p>
			</RulesSection>

			<RulesSection title="Playing the cards">
				<ul>
					<li>You <b>must follow the suit that was led</b> if you can — and a face-up card on
						top of one of your piles counts as a card you hold for this purpose.</li>
					<li>If you can't follow, play anything, including trump. Trumping is allowed but
						never compulsory.</li>
					<li>The highest trump wins the trick; if no trump was played, the highest card of the
						suit led wins. The winner leads the next trick.</li>
					<li>Trick 1 is odd (−1), trick 2 is even (+2), and so on alternating to trick 13.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Scoring">
				<p>
					Trick points are only the <b>yardstick</b> — the score comes from the contract:
				</p>
				<ul>
					<li>Declarer <b>makes</b> the contract (finishes with at least N trick points):
						declarer scores <b>N × N</b>. The defender scores nothing.</li>
					<li>Declarer <b>falls short</b>: the <b>defender</b> scores <b>(N − 1) + 4 for every
						point the declarer finished below N</b>.</li>
				</ul>
				<p>
					So a high contract is worth a great deal and costs a great deal. Bidding 3 and
					making it scores 9; bidding 3 and finishing on 1 gives your opponent 10.
				</p>
			</RulesSection>

			<RulesSection title="The thing to notice">
				<RulesTip>
					<p>
						You need high cards to <b>win</b> the +2 tricks — but you need <b>low</b> cards
						just as badly. Leading your smallest card into an odd trick forces your opponent
						to win it and eat the penalty. A hand of pure aces is a bad hand: you'll win
						everything, including all seven tricks you didn't want.
					</p>
				</RulesTip>
				<ul>
					<li><b>Count the parity, not the tricks.</b> Before you play a card, ask which
						trick number you're playing into.</li>
					<li><b>Losing the lead is a resource.</b> Whoever leads an odd trick usually eats it,
						so handing the lead over at the right moment is an attack.</li>
					<li><b>Your piles are a schedule, not a hand.</b> The order you burn through pile tops
						decides what you'll have available on trick 12 — plan it early.</li>
					<li><b>The face-up cards cut both ways.</b> Your opponent can see the bottom card of
						your middle pile too, and will play around it.</li>
					<li><b>Bid the number you can defend.</b> Because the set penalty is linear and the
						make bonus is squared, a level you're confident of beats a level you're hoping
						for.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				One round per game, head-to-head against a friend (share the room code) or the bot.
				Suits are shown by glyph as well as color, so red/black is never the only signal.
			</p>
		</>
	);
}
