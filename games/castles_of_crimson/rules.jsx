// Castles of Crimson's how-to-play content. Chrome comes from the shared RulesModal
// kit (shared/lobby.jsx) — this file is only the words, and rides CoC's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function CocRules() {
	return (
		<>
			<p className="rl-lead">
				You own a <b>duchy</b> — a personal board of empty hexagonal spaces, grouped into
				colored regions. Over the game you fill it with tiles: mines that pay you, ships that
				bring trade goods, buildings that give you extra actions, monasteries with unique
				powers. Filling a whole region scores points, and filling it <b>early</b> scores far
				more. Most victory points at the end wins.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "2–4 (vs the bot: 2)" },
				{ k: "Length", v: "40–60 minutes" },
				{ k: "You win by", v: "Most victory points after 5 phases" },
			]} />

			<RulesSection title="How the game is shaped">
				<p>
					The game is <b>5 phases of 5 rounds</b> — 25 turns each, and that's the entire
					clock. Every space in your duchy shows a <b>number from 1 to 6</b> and belongs to a
					<b> colored region</b>. To fill a space you need a die showing its number, and the
					tile you place must be the type that space's color calls for.
				</p>
				<p>
					You start with one castle placed in your duchy, 1 silver, 3 goods and no workers.
					Every tile you place afterward must be <b>adjacent to something you already own</b>,
					so your duchy grows outward from that castle.
				</p>
			</RulesSection>

			<RulesSection title="Your turn: two dice, two actions">
				<p>
					You roll <b>two dice</b>. Each die buys you <b>one</b> action, so you act twice per
					turn. Before using a die you may <b>spend a worker to change it by 1</b> (nudging a
					die back toward the number it actually rolled refunds that worker). The five actions:
				</p>
				<RulesDefs items={[
					{ t: "Take a tile", d: "From the depot whose number matches the die, into your storage. Storage holds 3 tiles — if it's full, something has to go." },
					{ t: "Place a tile", d: "From storage onto an empty space showing that die's number, adjacent to your duchy. This is how you actually score." },
					{ t: "Sell goods", d: "Sell a batch of goods whose number matches the die, for silver and VP." },
					{ t: "Buy a black tile", d: "From the central depot for 2 silver — any die value." },
					{ t: "Take 2 workers", d: "Any die value. Workers are your way of fixing bad rolls." },
				]} />
				<RulesTip>
					<p>
						Taking a tile and placing it are <b>two separate actions</b> needing two different
						die values. That's the core tension of the game: the tile you want and the space
						it goes into rarely match the dice you rolled.
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="What each tile does when you place it">
				<RulesDefs items={[
					{ t: "Castle", d: "Immediately take one extra action, at any die value you like. Chaining castles is a genuine strategy." },
					{ t: "Mine", d: "Pays you silver at the end of every phase for the rest of the game — so early mines are worth several times a late one." },
					{ t: "Ship", d: "Brings you a batch of trade goods and moves you up the turn order." },
					{ t: "Livestock", d: "Animal tiles that score VP the moment they're placed, and score much more when you group the same animal together." },
					{ t: "Building", d: "An instant effect: market, carpenter and church (take a tile into storage), warehouse (sell goods), boarding house (+4 workers), bank (+2 silver), town hall (place another tile), watchtower (+4 VP). Only one of each building type per region." },
					{ t: "Monastery", d: "One of 26 unique tiles, identified by its number, granting an ongoing power and/or an end-game scoring bonus." },
				]} />
			</RulesSection>

			<RulesSection title="Goods and selling">
				<p>
					Goods come in six colors, each tied to a number. Match a die to that number to sell
					<b> every goods tile of that color at once</b>: you get silver plus VP for each tile
					sold (2 VP per tile in a 2-player game, more with more players). You can hold at
					most three different colors at a time, so sell before a ship arrives and crowds you
					out.
				</p>
			</RulesSection>

			<RulesSection title="Scoring — the part that decides the game">
				<ul>
					<li><b>Completing a region</b> (every space of one colored area filled) scores by its
						size: <b>1 / 3 / 6 / 10 / 15 / 21 / 28 / 36</b> VP for regions of 1 to 8 spaces.</li>
					<li><b>Plus a phase bonus that shrinks all game</b> — <b>10, 8, 6, 4, 2</b> VP in
						phases 1 through 5. Finishing a 3-space region in phase 1 is worth 16 VP; the same
						region in phase 5 is worth 8.</li>
					<li><b>Color bonuses</b> — the first player to fill <i>every</i> space of a given color
						across their whole duchy takes the large bonus (5 VP in a 2-player game); the
						second player to do it takes the small one (2 VP).</li>
					<li><b>Selling goods</b> and <b>watchtowers</b> and <b>livestock</b> score as they
						happen.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Between phases, and the end">
				<ul>
					<li>At the start of each new phase the numbered depots are cleared and refilled with
						the same <b>types</b> of tile — the faint ghost outlines on the depots show you
						what's coming back.</li>
					<li>Your mines pay out silver at the end of every phase.</li>
					<li>After the last round, leftover resources score: <b>1 VP per goods tile</b>,
						<b> 1 VP per silver</b>, <b>1 VP per two workers</b>. Then any monastery end-game
						bonuses are added.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				Play a friend (2–4 seats, share the room code) or the bot at Easy / Hard / Expert.
				Expert runs a learned evaluation in your browser and plays a genuinely strong tempo
				game.
			</p>
		</>
	);
}
