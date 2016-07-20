import asyncio
import re
from challonge import Account, ChallongeException
from challonge_accounts import TournamentStateConstraint
from const import *
import math
from utils import AutoEnum


class TournamentState(AutoEnum):
    pending = ()
    underway = ()
    awaiting_review = ()
    complete = ()


def author_is_winner(csv_score):
    total_author = 0
    total_opponent = 0
    for s in re.findall(r'\d+-\d+', csv_score):
        split = s.split('-')
        if split[0] > split[1]:
            total_author += 1
        else:
            total_opponent += 1
    return total_author > total_opponent


def reverse_score(csv_score):
    newScore = []
    for s in re.findall(r'\d+-\d+', csv_score):
        split = s.split('-')
        newScore.append('{0}-{1}'.format(split[1], split[0]))
    return ','.join(newScore)


def verify_score_format(csv_score):
    result = re.compile('(\d+-\d+)(,\d+-\d+)*')
    return result.match(csv_score)


def match_sort_by_round(list_):
    return list_['round'] < 0, abs(list_['round'])


def player_sort_by_rank(list_):
    return list_['final-rank']


def get_date(date):
    r = re.match('(?P<year>(?:19|20)\d\d)/(?P<month>0[1-9]|1[012])/(?P<day>0[1-9]|[12][0-9]|3[01])', date)
    if r:
        return r.groupdict()
    else:
        return None


def get_time(time):
    r = re.match('(?P<hours>[01]\d|2[0-4]):(?P<minutes>[0-5]\d)', time)
    if r:
        return r.groupdict()
    else:
        return None

async def get_player(account, t_id, name):
    try:
        participants = await account.participants.index(t_id)
    except ChallongeException as e:
        return None, T_OnChallongeException.format(e)
    else:
        for x in participants:
            if x['name'] == name:
                return x['id'], None
        return None, None


async def get_players(account, t_id, p1_name, p2_name):
    try:
        participants = await account.participants.index(t_id)
    except ChallongeException as e:
        return None, None, T_OnChallongeException.format(e)
    else:
        p1_id = p2_id = None
        for x in participants:
            if x['name'] == p1_name:
                p1_id = x['id']
            elif x['name'] == p2_name:
                p2_id = x['id']
            if p1_id and p2_id:
                break
        return p1_id, p2_id, None


async def get_match(account, t_id, p1_id, p2_id):
    try:
        openMatches = await account.matches.index(t_id, state='open', participant_id=p1_id)
    except ChallongeException as e:
        return None, None, T_OnChallongeException.format(e)
    else:
        for m in openMatches:
            if m['player1-id'] == p1_id and m['player2-id'] == p2_id or m['player2-id'] == p1_id and m['player1-id'] == p2_id:
                is_reversed = m['player1-id'] == p2_id
                return m, is_reversed, None
    return None, None, None


async def update_score(account, t_id, m_id, score, winner_id):
    try:
        await account.matches.update(t_id, m_id, scores_csv=score, winner_id=winner_id)
    except ChallongeException as e:
        return None, T_OnChallongeException.format(e)
    else:
        return '✅ These results have been uploaded to Challonge', None


async def get_participants(account, t):
    if 'participants' in t:
        participants = t['participants']
    else:
        try:
            participants = await account.participants.index(t['id'])
        except ChallongeException as e:
            return None, T_OnChallongeException.format(e)

    return participants, None


async def get_open_matches(account, t):
    if 'matches' in t:
        matches = [m for m in t['matches'] if m['state'] == 'open']
    else:
        try:
            matches = await account.matches.index(t['id'], state='open')
        except ChallongeException as e:
            return None, T_OnChallongeException.format(e)

    return matches, None

async def _get_channel_desc_pending(account, t):
    desc = []
    desc.append('Tournament {0} ({1}) is pending with {2} participants'.format(t['name'], t['full-challonge-url'], t['participants-count']))
    if t['participants-count'] < 30:
        participants, exc = await get_participants(account, t)
        if exc:
            return None, exc

        desc.append('Registered participants:')
        participantsCount = len(participants)
        cols = 4
        rows = math.ceil(participantsCount / cols)
        participantsaArr = [[participants[x + y * cols]['name'] for x in range(cols) if x + y * cols < participantsCount] for y in range(rows)]
        desc.append('\n'.join([' '.join(participantsaArr[y]) for y in range(rows)]))

    return '\n'.join(desc), None


async def _get_channel_desc_underway(account, t):
    matchesrepr, exc = await get_current_matches_repr(account, t)
    if exc:
        return None, exc

    toReturn = 'Tournament {0} ({1}) is in progress with {2} participants\nOpen matches:\n{3}'.format(t['name'], t['full-challonge-url'], t['participants-count'], matchesrepr)
    return toReturn, None


async def _get_channel_desc_awaiting_review(account, t):
    return 'Tournament is awaiting review from organizers', None


async def _get_channel_desc_complete(account, t):
    rankingRepr, exc = get_final_ranking_repr(account, t)
    if exc:
        return None, exc

    return 'Tournament is finished!\n' + rankingRepr, None


async def get_channel_desc(account, t):
    if t['state'] == 'pending':
        return await _get_channel_desc_pending(account, t)
    if t['state'] == 'underway':
        return await _get_channel_desc_underway(account, t)
    if t['state'] == 'awaiting_review':
        return await _get_channel_desc_awaiting_review(account, t)
    if t['state'] == 'complete':
        return await _get_channel_desc_complete(account, t)

    print('[get_channel_desc] Unreferenced tournament state: ' + t['state'])
    return None, None


async def validate_tournament_state(account, t_id, constraint):
    try:
        t = await account.tournaments.show(t_id)
    except ChallongeException as e:
        raise e
    else:
        if t['state'] == 'pending' and constraint & TournamentStateConstraint.Pending:
            return True
        if t['state'] == 'underway' and constraint & TournamentStateConstraint.Underway:
            return True
        if t['state'] == 'awaiting_review' and constraint & TournamentStateConstraint.AwaitingReview:
            return True
        if t['state'] == 'complete' and constraint & TournamentStateConstraint.Complete:
            return True

        return False

async def get_current_matches_repr(account, t):
    matches, exc = await get_open_matches(account, t)
    if exc:
        return None, exc

    participants, exc = await get_participants(account, t)
    if exc:
        return None, exc

    matches.sort(key=match_sort_by_round)

    if t['tournament-type'] == 'single elimination':
        bracketType = 1
    else:
        bracketType = 0

    desc = []
    for m in matches:
        if t['tournament-type'] in ['single elimination', 'double elimination']:
            if m['round'] > 0 and bracketType != 1:
                desc.append('Winners bracket:')
                bracketType = 1
            elif m['round'] < 0 and bracketType != 2:
                desc.append('Losers bracket:')
                bracketType = 2
        else:
            if bracketType == 0:
                desc.append('Open matches:')
                bracketType = 1

        p1 = [p for p in participants if p['id'] == m['player1-id']][0]
        p2 = [p for p in participants if p['id'] == m['player2-id']][0]
        desc.append('`{0}` 🆚 `{1}`'.format(p1['name'], p2['name']))
    return '\n'.join(desc), None


async def get_final_ranking_repr(account, t):
    participants, exc = await get_participants(account, t)
    if exc:
        return None, exc

    info = []
    info.append('Final standings:')
    participants.sort(key=player_sort_by_rank)
    lastRank = 0
    for p in participants:
        if lastRank < p['final-rank']:
            info.append('Position #%d' % p['final-rank'])
            lastRank = p['final-rank']
        info.append('\t' + p['name'])
    return '\n'.join(info), None


async def get_open_match_dependancy(account, t_id, m, p_id):
    if m['player1-id'] == p_id:
        if 'player2-prereq-match-id' in m:
            waiting_on_match_id = m['player2-prereq-match-id']
            waiting_for_loser = m['player2-is-prereq-match-loser']
        else:
            return None, '✅ You have a pending match with no dependancy!?'
    elif m['player2-id'] == p_id:
        if 'player1-prereq-match-id' in m:
            waiting_on_match_id = m['player1-prereq-match-id']
            waiting_for_loser = m['player1-is-prereq-match-loser']
        else:
            return None, '✅ You have a pending match with no dependancy!?'
    else:
        return None, '✅ Couldn\'t find participant'

    try:
        waiting_on_m = await account.matches.show(t_id, waiting_on_match_id)
    except ChallongeException as e:
        return None, T_OnChallongeException.format(e)
    else:
        loser_txt = '`Loser`' if waiting_for_loser else '`Winner`'
        if waiting_on_m['player1-id'] == 0 or waiting_on_m['player2-id'] == 0:
            return 'you are waiting for more than one match', None
        else:
            try:
                p1 = await account.participants.show(t_id, waiting_on_m['player1-id'])
                p2 = await account.participants.show(t_id, waiting_on_m['player2-id'])
            except ChallongeException as e:
                return None, T_OnChallongeException.format(e)
            else:
                return 'you are waiting on the %s of %s 🆚 %s' % (loser_txt, p1['name'], p2['name']), None


async def get_next_match(account, t_id, name):
    p_id, exc = await get_player(account, t_id, name)
    if exc:
        return None, exc
    elif p_id:
        try:
            openMatches = await account.matches.index(t_id, state='open', participant_id=p_id)
        except ChallongeException as e:
            return None, T_OnChallongeException.format(e)
        else:
            if len(openMatches) > 0:
                if openMatches[0]['player1-id'] == p_id:
                    opponent_id = openMatches[0]['player2-id']
                else:
                    opponent_id = openMatches[0]['player1-id']

                try:
                    opponent = await account.participants.show(t_id, opponent_id)
                except ChallongeException as e:
                    return None, T_OnChallongeException.format(e)
                else:
                    return '✅ %s, you have an open match 🆚 %s' % (name, opponent['name']), None
            else:
                try:
                    pendingMatches = await account.matches.index(t_id, state='pending', participant_id=p_id)
                except ChallongeException as e:
                    return None, T_OnChallongeException.format(e)
                else:
                    if len(pendingMatches) > 0:
                        msg, exc = await get_open_match_dependancy(account, t_id, pendingMatches[0], p_id)
                        if exc:
                            print(exc)
                            return '✅ %s, you have a pending match. Please wait for it to open' % name, None
                        else:
                            return '✅ %s, %s' % (name, msg), None
                    else:
                        return '✅ %s, you have no pending nor open match. It seems you\'re out of the tournament' % name, None
    else:
        return None, '❌ Participant \'%s\' not found' % name
