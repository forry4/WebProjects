// Spender's how-to-play content. Chrome (panel, scrolling, typography) comes from
// the shared RulesModal kit — this file is ONLY the words, so the rules can grow
// without touching the 3,000-line screen file, and it rides Spender's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function SpenderRules() {
	return (
		<>
			<p className="rl-lead">
				You are a merchant buying gem mines and workshops. Every card you buy pays you a
				permanent <b>discount</b> on everything you buy afterwards, so cheap early cards make
				expensive later cards affordable. Those expensive cards are the ones worth
				<b> prestige points</b> — and prestige wins the game.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "2–4 (vs the bot: 2)" },
				{ k: "Length", v: "20–40 minutes" },
				{ k: "You win by", v: "15 prestige (Classic) or 21 (Long)" },
			]} />

			<RulesSection title="What's on the table">
				<ul>
					<li><b>The gem bank</b> — five colors (white, blue, green, red, black) plus <b>gold</b>.
						There are 4 of each color in a 2-player game, 5 with 3 players, 7 with 4, and always
						5 gold.</li>
					<li><b>Three rows of cards.</b> The bottom row is cheap and mostly worth 0 points, the
						middle row costs more and pays 1–3 points, the top row is expensive and pays 3–5
						points. Four cards of each row are face up; buying or reserving one immediately
						flips a replacement from that row's deck.</li>
					<li><b>Nobles</b> — one more than the number of players. They're worth
						<b> 3 points</b> each and cannot be bought; they come to you when you meet their
						requirement.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Your turn — do exactly one of these">
				<RulesDefs items={[
					{ t: "Take 3 gems", d: "One each of three different colors." },
					{ t: "Take 2 gems", d: "Both the same color — allowed only if at least 4 of that color are still in the bank." },
					{ t: "Buy a card", d: "From the face-up rows or from your own reserve, by paying its cost." },
					{ t: "Reserve a card", d: "Put a face-up card (or the unseen top card of a deck) into your hand and take 1 gold. You may hold at most 3 reserved cards." },
				]} />
				<p>
					That's the whole game — there is no other action, and you must take one. You cannot
					pass, and you cannot combine two of them in one turn.
				</p>
			</RulesSection>

			<RulesSection title="Buying, bonuses and gold">
				<p>
					A card's cost is printed down its left edge — for example 2 white + 1 blue. You pay
					those gems back to the bank. But every card you have <b>already</b> bought shows a
					gem in its corner: that is a permanent <b>bonus</b>, and each bonus of a color
					reduces the cost of that color by 1 on every future purchase, forever. Own three
					white cards and a "3 white" cost becomes free.
				</p>
				<p>
					<b>Gold is a wild.</b> One gold can stand in for one gem of any color when you buy.
					It's the only way to take a token without spending your whole action on tokens, and
					it's how you cover the last gem or two of a card you can nearly afford.
				</p>
			</RulesSection>

			<RulesSection title="Reserving">
				<p>
					Reserving does two things: it takes a gold, and it puts the card <b>out of your
					opponents' reach</b> — a reserved card is yours to buy later, and nobody else can
					touch it. You may reserve the top card of a deck without looking at it; that card is
					hidden from everyone until you buy it.
				</p>
				<p>Three reserved cards is the maximum. Reserved cards are bought like any other card.</p>
			</RulesSection>

			<RulesSection title="Nobles">
				<p>
					Each noble lists a requirement in <b>card bonuses</b>, not gems — for example 4 red
					and 4 green, or 3 black, 3 red and 3 white. At the end of your turn, if your bonuses
					meet a noble's requirement, that noble visits you for 3 points. If more than one
					qualifies you choose which visits (only one per turn). You never spend anything on a
					noble, and you can never "take" one on purpose — you just build toward it.
				</p>
			</RulesSection>

			<RulesSection title="The 10-gem limit">
				<p>
					You may end your turn holding at most <b>10 tokens</b>, gold included. If a take puts
					you over, you discard back down to 10 before play passes on. Bonuses from cards are
					not tokens and never count toward this.
				</p>
			</RulesSection>

			<RulesSection title="Ending the game">
				<p>
					The moment a player reaches the target — <b>15</b> prestige in Classic, <b>21</b> in
					Long — the round is played out so that everyone has had the same number of turns.
					Then the highest prestige wins. A tie goes to the player who bought <b>fewer
					cards</b>, since they got there more efficiently.
				</p>
			</RulesSection>

			<RulesSection title="At the table">
				<ul>
					<li>Click gem tokens to select them, then press <b>Take</b>. Click a selected gem
						again to put it back.</li>
					<li>Click a card to select it, then press <b>Buy</b>. Cards you can't currently afford
						are dimmed.</li>
					<li>To reserve: click the <b>gold coin</b>, then click any card (or a face-down deck) —
						or select the card first and then click gold. Either order works.</li>
				</ul>
			</RulesSection>

			<RulesSection title="How to actually be good at this">
				<RulesTip>
					<p>
						The trap for new players is buying points too early. Prestige on a level-1 card is
						almost worthless; the <b>bonus</b> is the real payout. A hand of 6–8 cheap cards
						turns 5-point cards from unaffordable into a two-turn purchase, and that engine is
						what wins.
					</p>
				</RulesTip>
				<ul>
					<li><b>Pick a target early.</b> Look at the top row, choose a card you want, and take
						gems that move you toward it — not whatever is most plentiful.</li>
					<li><b>Spread your bonuses to match a noble.</b> Nobles are 3 free points and are
						often the actual margin of victory. Two nobles is usually a win.</li>
					<li><b>Don't hoard tokens.</b> Ten gems sitting in your hand are ten gems your
						opponents can't use, but they score nothing. Convert them.</li>
					<li><b>Watch what your opponent is collecting.</b> If they're one turn from a card you
						can see they need, reserving it costs you a turn and costs them their plan.</li>
					<li><b>Count the last lap.</b> Near 15 points, work out whether you can finish before
						the leader triggers the final round — sometimes a 3-point card now beats a
						5-pointer two turns away.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				Play 2–4 players against friends (share the room code), or head-to-head against the
				bot. The bot's top tiers run a real search and will punish a slow start.
			</p>
		</>
	);
}
