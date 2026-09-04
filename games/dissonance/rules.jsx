// Dissonance's how-to-play content. Chrome comes from the shared RulesModal kit.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs } from "../../shared/lobby.jsx";

export default function DissonanceRules() {
	return (
		<>
			<p className="rl-lead">
				Dissonance is a two-player trick-taking game where winning is not always good.
				Even-numbered tricks are worth <b>+2</b>; odd-numbered tricks cost <b>−1</b>.
				The art is choosing which tricks to take.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "1–2 (friend or bot)" },
				{ k: "Length", v: "A few minutes per round" },
				{ k: "You win by", v: "Being first to 200 points" },
			]} />

			<RulesSection title="The deck and the deal">
				<p>
					The 32-card deck has <b>7, 8, 9, 10, J, Q, K and A</b> in each suit. You
					each receive seven cards in hand and three two-card piles. Only the top card
					of a pile is playable; when it is gone, the card below becomes visible and
					playable. One middle-pile card starts face-up, while six cards sit out of
					the round unseen.
				</p>
			</RulesSection>

			<RulesSection title="The auction">
				<p>
					Before trick play, bid a <b>level from 1–10</b> and a denomination: one
					of the four suits or no-trump. The winning bid makes its player declarer;
					the denomination becomes trump and the level is the trick-point target.
				</p>
				<RulesDefs items={[
					{ t: "Opening", d: "The opener must make a bid." },
					{ t: "Raising", d: "Beat the standing bid with a higher denomination at the same level, or a higher level in a denomination you have not already named. You may also pass." },
					{ t: "Jumps", d: "If the final bid jumps levels, a failed contract costs the defender an extra 5 points for each level jumped." },
					{ t: "Lead", d: "The declarer leads trick one — an odd, negative trick." },
				]} />
			</RulesSection>

			<RulesSection title="Playing tricks">
				<ul>
					<li>You must follow the suit led when you can. Otherwise, play any available card; trumping is allowed but never required.</li>
					<li>The highest trump wins. With no trump, the highest card in the led suit wins.</li>
					<li>The winner leads the next trick. Tricks alternate: 1st, 3rd, 5th and so on are −1; 2nd, 4th, 6th and so on are +2.</li>
				</ul>
			</RulesSection>

			<RulesSection title="The talon and Null">
				<p>
					After the auction, the declarer may take one of three revealed talon cards,
					then discard one hand card face-down. If the declarer takes no scoring trick
					at all, they instead make <b>Null</b> for a flat <b>20 points</b>.
				</p>
			</RulesSection>

			<RulesSection title="Kontra">
				<p>
					After the talon, the defender may call <b>Kontra</b> or let the contract
					stand. Kontra doubles the contract's round payout, whether the declarer makes
					it or is set. It is the defender's chance to raise the stakes on a hand they
					believe is misjudged.
				</p>
			</RulesSection>

			<RulesSection title="Scoring">
				<ul>
					<li><b>Make the contract:</b> the declarer scores N × N, plus 1 for every trick point above N.</li>
					<li><b>Miss the contract:</b> the defender scores 5 for every point short, plus any jump penalty from the auction.</li>
				</ul>
				<p>Scores carry across rounds. The first player to 200 wins the match.</p>
			</RulesSection>

			<p className="rl-note">
				These rules describe Classic mode. Skat, Minor, Dummy and Quartet are beta
				modes with their own variations, available from the game setup.
			</p>
		</>
	);
}
