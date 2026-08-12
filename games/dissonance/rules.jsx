// Dissonance's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Dissonance's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function DissonanceRules() {
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
				{ k: "Length", v: "A few minutes a round; a match is about 9 of them" },
				{ k: "You win by", v: "Being first to 150 points (100 in Skat mode, 25 in Minor)" },
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

			<RulesSection title="Two auctions — pick one when you create the game">
				<p>
					The deal, the piles, the talon and the card play below are the same either
					way. Only <b>how you arrive at a contract</b> changes:
				</p>
				<RulesDefs items={[
					{ t: "Classic", d: "Bid a level and a denomination together. Simple, and your bid tells your opponent what you intend to play." },
					{ t: "Skat", d: "Bid a bare NUMBER. Only after winning do you name the game — and many games clear the same number, so the auction happens behind the denomination. Skat also scores differently: the CARDS you capture are worth points, not the trick numbers — see its section." },
				]} />
				<p className="rl-note">
					Classic is described first; the Skat auction has its own section further
					down. A room's auction is fixed when it's created and shown as a badge in
					the lobby.
				</p>
			</RulesSection>

			<RulesSection title="The auction">
				<p>
					Before playing, you bid for the contract. A bid is a <b>number (1–10)</b> and a
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
					After the auction, the declarer is shown <b>three</b> of the six talon cards
					and may take <b>one</b> into hand, discarding a hand card face-down in its place
					(pile cards can't be swapped). The defender is told <i>that</i> a swap happened —
					never which cards. Winning the auction buys information as well as the contract.
				</p>
			</RulesSection>

			<RulesSection title="Null — the way out of a hand gone wrong">
				<p>
					You never bid Null. It sits under <i>every</i> contract at once: if you are the
					declarer and you finish the round having won <b>no scoring trick at all</b> — no
					+2 trick in classic, no trick worth more than zero in Skat mode — you score
					a flat <b>20</b> — in classic and Skat mode alike — instead of being set, whatever you
					declared, and however far short of it you finished.
				</p>
				<p>
					So a contract you can no longer make is not simply lost. Stop fighting for the
					scoring tricks, duck every one of them, and the hand pays you instead of your
					opponent. Your opponent's job changes with it: they now have to <b>force a
					single +2 trick on you</b>, and one is enough.
				</p>
				<RulesTip>
					<p>
						Winning a −1 trick is legal and costs you nothing directly — but it puts you
						<b> on lead into the +2 trick that follows</b>, the one seat you can't duck
						from. The odd tricks are not free.
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="Kontra — the defender raises the stakes">
				<p>
					Once the contract is settled and the declarer has taken their talon card,
					the <b>defender</b> gets one decision: <b>Kontra</b>, or let it stand.
					It changes both ends of the bet, and deliberately not by the same amount:
				</p>
				<ul>
					<li>Declarer <b>makes</b> it: they score <b>double</b> — 2 × (N × N + 10)
						instead of N × N + 10, overtricks included.</li>
					<li>Declarer <b>falls short</b>: you score <b>2 × (N + 10)</b>, and every point
						they finish below N costs them <b>more than the last</b> — 6, then 7, then
						8, then 9 — instead of a flat 5 each.</li>
					<li><b>Null is untouched.</b> A declarer who wins no +2 trick still scores
						the flat 20, Kontra or not.</li>
				</ul>
				<p>
					That rising scale is the whole point. It barely touches a declarer who
					misses by one — which is what most failed contracts do — and it bites hard
					on one who finishes miles short, which is what a <b>sacrifice</b> looks
					like. A level-6 contract one short pays you 38; four short, 62.
				</p>
				<RulesTip>
					<p>
						<b>What it's for.</b> When you're about to make a big contract, your
						opponent's best move is often to <b>outbid you with nothing</b> — 6♣ over
						your 5♠ — because being set costs them less than letting you score 35.
						Kontra is how you charge them properly for that. Note the escape,
						though: a declarer who hasn't yet won a +2 trick can duck every one of
						them and take Null instead, and Kontra doesn't touch Null. So the bet
						pays best against someone who has <i>already</i> won a scoring trick and
						can no longer get out that way. (Skat mode's Kontra is its own,
						symmetric version — everything ×2 whichever way it falls, and the
						declarer may answer <b>Re</b>; see its section below.)
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="Skat mode — bid a number, name the game later">
				<p>
					In the classic auction the level is <i>both</i> the price and the task, so
					naming your bid announces your plan. Skat mode splits them. You bid a
					number; the number is only a <b>price</b>, and you decide what to play
					after you've won.
				</p>
				<p>
					A game is worth <b>base × level</b>, and the price is set by
					<i> colour</i>: <b>the reds ♦♥ cost 2, the blacks ♠♣ cost 3, Grand
					costs 4 and no-trump costs 5</b>. The level is still the trick points
					you promise to score — but Skat mode counts them differently.
				</p>
				<RulesTip>
					<p>
						<b>Skat scores the cards, not the trick number.</b> Every card you
						capture is worth points: <b>9, 10, J and Q are +2 each</b>;{" "}
						<b>7, 8, K and A are −1 each</b>. A trick pays its winner the sum
						of its two cards — <b>−2, +1 or +4</b> — so the board shows each
						card's worth in its corner. The aces and kings still <i>win</i>{" "}
						tricks, but they poison what they capture; the cards worth taking
						sit in the middle, where they rarely win a trick on their own. Six
						cards sit out of every deal, so a round's total pool moves with the
						deal — around 13 on average.
					</p>
				</RulesTip>
				<p>
					<b>Grand</b> is a sixth game, and skat mode is the only place you can
					buy it. The four <b>10s are trump</b> and they leave their suits
					entirely: the 10♦ is <i>not</i> a diamond, so it will not answer a
					diamond lead, and a hand whose only diamond is the 10 is <b>void</b> in
					diamonds. Lead a 10 and your opponent must play a 10 if they hold one.
				</p>
				<RulesTip>
					<p>
						<b>The second 10 played wins.</b> They are all tens, so there is
						nothing to rank them by — which makes leading one a way to
						<i> lose</i> a trick on purpose. That is a real tool for refusing a
						bad trick — just remember the 10 itself is worth +2 to whoever
						takes it. With only four trumps in
						the deck (and some of them usually out of play), Grand plays much
						closer to no-trump than to a suit game — which is why it is priced
						just below it.
					</p>
				</RulesTip>
				<RulesTip>
					<p>
						<b>Collisions are the point.</b> 12 is ♦6, and ♥6, and ♠4, and ♣4,
						and Grand 3. Bid 12 and your opponent learns the price of your hand,
						never its shape. A hand playable in two denominations can bid higher
						<i> safely</i> than an equally strong hand playable in one —
						flexibility becomes a resource with a price. The two suits of a
						colour cost the same, so choosing between them is a question about
						your cards and nothing else.
					</p>
				</RulesTip>
				<RulesTip>
					<p>
						<b>You must head the trick.</b> If you can follow suit and you
						hold a card that beats the one led, you have to play one — no
						sliding a 7 under a winner. (Void in the suit you are still
						free to do anything, and never have to trump.)
					</p>
					<p>
						It sounds like a restriction and it is really a weapon, because
						of what the card values are: <b>lead a king and the ace has to
						answer it</b>, so your opponent takes a trick worth −2 with the
						two worst cards in the deck. Without the rule they simply duck a
						9 under your king and <i>you</i> eat it. So the cards nobody
						wants become the way you attack, and holding a bare ace is a
						real exposure.
					</p>
				</RulesTip>
				<RulesDefs items={[
					{ t: "The auction", d: "Ascending numbers, taking turns. Either player may pass — including the opener, because here passing hands the opponent the talon and the lead at THEIR price, rather than being an escape from a forced bad contract. Both passing throws the hand in and redeals." },
					{ t: "Talon or Hand", d: "Win it and you choose: look at the three talon cards and maybe swap one in, or decline to look at all and play HAND for ×2. Looking and then standing pat is not Hand — you saw them." },
					{ t: "Declare", d: "Name a denomination and a level whose value reaches your bid. Declaring the minimum is normal; declaring higher is voluntary and pays more." },
					{ t: "Sharp / Open", d: "Before trick 1 you may promise your level PLUS 2 (Sharp, +1 to the multiplier) and then play with your hand face up (Open, +1 again). They stack by addition: Hand + Sharp + Open is ×4." },
					{ t: "Kontra", d: "The defender, who has just learned what game they're facing, may double everything. The declarer may Re it back to ×4 of the announced total." },
				]} />
				<p>
					<b>Scoring.</b> Trick points are the card points above. Make everything
					you announced and you score{" "}
					<b>value × multiplier</b>, plus <b>1 for every card point past your
					target</b>. Miss any part of it — the level, or the Sharp margin on top —
					and your opponent scores that same number, plus 5 for every point you
					finished short. The overtrick bonus is flat: 1 a point whatever the
					contract cost, so Kontra never multiplies it.
				</p>
				<p>
					So the escalation doesn't stop when the auction does. Winning cheap at 6
					and quietly declaring ♦3 is legal and pays 6; the same hand announcing
					Hand + Sharp pays 18 out of the identical auction. Your real bid is the one
					you make against yourself, after your opponent is out of the loop — and
					then they get the last word.
				</p>
			</RulesSection>

			<RulesSection title="Minor mode — even tricks pay only +1">
				<p>
					The classic auction, played in a harsher currency: an even trick pays{" "}
					<b>+1</b> instead of +2, and the odd ones still cost 1. The two trick
					scores now add up to <b>−1</b> — winning <i>everything</i> scores minus
					one — so even more than in classic, the game is about which tricks you
					refuse.
				</p>
				<ul>
					<li>A perfect declarer tops out at <b>6</b> points, so contracts run{" "}
						<b>1–6</b> instead of 1–10. Level 1 is a real ask: the average split
						is below zero, so every contract has to be won.</li>
					<li>Scoring keeps classic's shape at the smaller scale: make{" "}
						<b>N²</b> plus 1 per overtrick, fall short and your opponent scores{" "}
						<b>N plus 2 per point short</b> — cheaper per point than classic's 5,
						because the payoffs are about a quarter the size. Classic's flat ±10
						stake doesn't apply here — at this scale it would drown the contract.</li>
					<li><b>Null pays 6</b> — exactly a made level-1 contract played to its
						ceiling, the relationship classic's Null had before the flat stake
						re-anchored it to 20.</li>
					<li>The Kontra works unchanged, ramp and all. The <b>match plays to
						25</b>, which buys about the same number of rounds as classic's 150.</li>
				</ul>
				<RulesTip>
					<p>
						With par below zero, the <i>defender</i> starts ahead — a declarer who
						can't get there should be thinking about ducking to Null from early
						on, and a defender should be thinking about forcing one even trick on
						them to break it.
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="Dummy mode — a third hand on the table">
				<p>
					A <b>three-seat</b> game between two players, off a <b>40-card
					deck</b> — the usual 32 plus a <b>5</b> and a <b>6</b> in each suit,
					because three hands of thirteen do not come out of 32. Everyone gets
					the same thirteen cards as any other mode (7 in hand plus three
					2-card piles), one card sits out, and there are <b>thirteen tricks
					of three cards</b>. Card scoring, and the classic auction — no
					talon. The 5s and 6s are worth <b>nothing</b>: the only cards in the
					game that neither pay you nor cost you, so they are what you throw
					when you want no part of a trick.
				</p>
				<p>
					The third hand is the <b>dummy</b>, and it is <b>face up from the
					deal</b>: both of you can read every card in it. Its outer pile
					bottoms stay hidden from <i>everyone</i>, so it is open, not solved.
				</p>
				<RulesDefs items={[
					{ t: "No following suit", d: "Play ANY card you can reach, always — this is the one mode that does not make you follow the suit led. Nobody can be forced into a trick they do not want, and the player answering last always has a real choice." },
					{ t: "Whoever leads plays it", d: "The dummy belongs to the player who leads the trick — so you are choosing two of the three cards, and the opponent answers last." },
					{ t: "It always plays second", d: "Leader, then the dummy, then the other player. The dummy never leads: a trick it wins leaves the lead where it was." },
					{ t: "Command follows the lead", d: "Win a trick and you take the dummy with it. Lose the lead and you hand it over." },
				]} />
				<RulesTip>
					<p>
						<b>The dummy is a prize, not a gift.</b> Because command follows
						the lead, winning a trick buys you the third hand for the next
						one — and in a game where taking tricks costs points, that is a
						real trade: eat a bad trick now to control two of three cards
						next time.
					</p>
					<p>
						The move to look for: lead low from your own hand, drop one of
						the dummy's big cards on it, and dare your opponent to take a
						trick they do not want.
					</p>
				</RulesTip>
				<p className="rl-note">
					The searching tiers (Hard, Expert) do not play this mode — their
					solver only understands two hands — so a Dummy game against the
					computer is Easy or Normal.
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
					<li><b>Dummy mode only:</b> you do <b>not</b> have to follow suit at
						all — any card you can reach is legal. With three cards to a
						trick and the points sitting in the cards themselves, being able
						to refuse a trick is what gives the last player a real decision.
						Every other mode makes you follow.</li>
					<li>Trick 1 is odd (−1), trick 2 is even (+2), and so on alternating to trick 13.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Scoring">
				<p>
					Trick points are only the <b>yardstick</b> — the score comes from the contract:
				</p>
				<ul>
					<li>Declarer <b>makes</b> the contract (finishes with at least N trick points):
						declarer scores <b>N × N, plus a flat 10</b>, plus <b>1 for every trick
						point past N</b>. The defender scores nothing.</li>
					<li>Declarer <b>falls short</b>: the <b>defender</b> scores <b>N + 10, plus 5 for
						every point the declarer finished below N</b>.</li>
				</ul>
				<p>
					The flat 10 rides on both ends — every contract carries the same stake on top
					of its level, win or lose, so a contract is only worth holding if you believe
					in it. Bidding 3 and making it scores 19; bidding 3 and finishing on 7 scores
					23; bidding 3 and finishing on 1 gives your opponent 23.
				</p>
				<RulesTip>
					<p>
						<b>Overtricks mean no trick is ever dead.</b> Getting home used to end the
						hand for you — the contract paid the same whether you finished on your
						number or five past it. Now every point after it is worth another, so the
						back half of a won hand is still worth playing, and the defender still has
						something to take off you. It also means <b>every round runs all thirteen
						tricks</b>.
					</p>
				</RulesTip>
				<p>
					<b>A game is a match, not a deal.</b> Rounds are scored onto a running total
					and the first player past the target — <b>150</b> in classic, <b>100</b> in
					Skat mode — wins. That's usually nine or ten rounds either way. One deal can
					simply be bad; over a match the deals even out and what's left is your bidding.
					Whoever opens the bidding alternates every round — opening means naming a
					contract before you know anything about their hand, and in classic mode you
					aren't allowed to pass.
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
				Rounds are played to a running total, head-to-head against a friend
				(share the room code) or the bot.
				Suits are shown by glyph as well as color, so red/black is never the only signal.
			</p>
		</>
	);
}
