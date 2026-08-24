// Where Wolf?'s how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides WW's own chunk.
import React from "react";
import { RulesFacts, RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

export default function WhereWolfRules() {
	return (
		<>
			<p className="rl-lead">
				One night, one vote, one game. Everyone is secretly dealt a role. The werewolves want
				to survive the morning vote; everyone else wants at least one werewolf dead. Nobody is
				eliminated early and nobody sits out — the whole game is a single night of secret
				actions followed by one argument.
			</p>

			<RulesFacts items={[
				{ k: "Players", v: "3–10, one phone each" },
				{ k: "Length", v: "About 10 minutes" },
				{ k: "You win by", v: "Your team's condition — see below" },
			]} />

			<RulesSection title="Setup">
				<ul>
					<li>The host builds a deck of exactly <b>players + 3</b> role cards. Everyone is dealt
						one at random; the <b>3 extra cards sit face-down in the center</b> and belong to
						nobody.</li>
					<li>Because 3 cards are unused, you can never be sure which roles are actually in
						play — a game with two werewolf cards may have zero werewolves at the table.</li>
					<li>Everyone can see <b>which roles are in the deck</b>, just not who has what.</li>
				</ul>
			</RulesSection>

			<RulesSection title="The one rule that confuses everybody">
				<RulesTip>
					<p>
						The role you were <b>dealt</b> is the role you act as during the night. The card
						sitting in front of you when the night <b>ends</b> is the role you are for
						scoring. Those can be different — and if someone swapped your card, you won't
						know. You can genuinely be a werewolf who spent the night believing they were a
						villager, and you still lose with the wolves.
					</p>
				</RulesTip>
			</RulesSection>

			<RulesSection title="The night">
				<p>
					Roles wake in a fixed order, one at a time, each for a fixed few seconds. Your phone
					tells you when it's your turn and what you may do:
				</p>
				<RulesDefs items={[
					{ t: "Werewolves", d: "Wake and see each other. If you are the only werewolf, you may instead peek at one center card." },
					{ t: "Minion", d: "Sees who the werewolves are — but they do not see the minion. You are on the wolves' team." },
					{ t: "Masons", d: "The two masons see each other. Seeing no other mason means the other mason card is in the center… or you're being lied to." },
					{ t: "Seer", d: "Look at one other player's card, or at two of the three center cards." },
					{ t: "Robber", d: "Swap your card with another player's, then look at your new card. You act as the robber all night regardless." },
					{ t: "Troublemaker", d: "Swap two OTHER players' cards without looking at either." },
					{ t: "Drunk", d: "Swap your card with a center card, blind. You do not get to look. You will not know what you are." },
					{ t: "Insomniac", d: "At the end of the night, look at your own card to see whether it changed." },
					{ t: "Villager, Tanner, Hunter", d: "No night action — but the tanner and hunter change how the vote resolves (below)." },
				]} />
				<p>
					Every role in the deck is announced during the night even if all its copies are in
					the center, so silence never gives anything away.
				</p>
			</RulesSection>

			<RulesSection title="The day">
				<p>
					Everyone wakes and talks, on a timer. This is the actual game: claim a role, ask
					people to account for what they saw, and work out who is lying. Because swaps
					happen, two players can both be telling the truth and still contradict each other.
				</p>
			</RulesSection>

			<RulesSection title="The vote">
				<ul>
					<li>When the timer runs out, everyone votes at the same time for one player.</li>
					<li>The player with the <b>most votes dies</b>. If several tie for most, <b>all of
						them die</b>.</li>
					<li>If nobody receives at least 2 votes, <b>nobody dies</b>.</li>
					<li>A <b>hunter</b> who dies also kills whoever they voted for.</li>
				</ul>
			</RulesSection>

			<RulesSection title="Who wins">
				<RulesDefs items={[
					{ t: "Village", d: "Wins if at least one WEREWOLF card dies. If there is no werewolf in play at all, the village wins only if nobody dies." },
					{ t: "Werewolves", d: "Win if a werewolf is in play and no werewolf dies. The minion wins with them — and killing the minion is not a werewolf death." },
					{ t: "Tanner", d: "Wins only by being killed. A tanner death with no werewolf death also BLOCKS the werewolf win — the tanner wins alone." },
				]} />
				<p>
					Teams are decided by the card in front of you at dawn, not the one you were dealt.
				</p>
			</RulesSection>

			<RulesSection title="Tips for your first game">
				<ul>
					<li><b>Claim early and specifically.</b> "I'm the seer, I saw Sam's villager card" is
						checkable. Staying quiet reads as a wolf.</li>
					<li><b>If you're a wolf, claim a role that was in the deck</b> and give a boring,
						consistent story. Claiming the drunk is safe — the drunk knows nothing.</li>
					<li><b>Two people claiming the same role is normal</b>, not proof: the robber, the
						troublemaker and the drunk all create honest confusion.</li>
					<li><b>Remember the center exists.</b> "No one claimed seer" usually means the seer
						card is in the middle, not that someone is hiding.</li>
					<li><b>If you might be the tanner, act like it's a bad night.</b> The tanner's job is
						to be convincingly suspicious.</li>
				</ul>
			</RulesSection>

			<p className="rl-note">
				Humans only — no bots. Everyone needs their own device; the app narrates the night out
				loud, so one person can play it from a speaker while everyone acts on their own phone.
			</p>
		</>
	);
}
