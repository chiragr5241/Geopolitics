#!/usr/bin/env python3
"""
One-shot seed: register the YouTube channel list into data/sources.csv.

Kept in the repo (like migrate_data.py) as the record of where the YouTube
half of the registry came from. Re-running is safe — upsert() merges, so a
channel listed under several topics accumulates categories instead of being
duplicated, and a re-run after the puller has resolved channel ids will not
clobber them.

Channel ids are deliberately NOT hardcoded here. A guessed id would be a
fabricated fact; instead each row carries the channel's @handle and
pull_youtube.py --resolve-channels fetches the real channelId from YouTube and
writes the feed_url. A handle that doesn't resolve is flagged `unverified` for
the routine to fix — the same path a user-typed source takes.

Every channel gets an explicit `yt-` source_id. That matters: several channels
share a name with an outlet already in the registry (BBC News, CNN, CNBC, NPR,
NBC News, Forbes, The Wall Street Journal…), and letting upsert() resolve those
by name merged the video channel INTO the wire source — which flipped
`bbc-world` to kind=youtube/scope=video and would have silently stopped the BBC
RSS pull. An organisation's YouTube channel is a DIFFERENT source from its
wire: different cadence, different content, and one is hidden from the feed
while the other is the feed.

Usage:  python3 scripts/seed_youtube_sources.py [--dry-run]
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from source_registry import (load_sources, save_sources, upsert, slugify,  # noqa: E402
                             YOUTUBE_PREFIX, all_categories)

# (topic, [channel names…]) — verbatim from the user's list, order preserved.
# A name appearing under several topics is one channel with several categories.
TOPICS = [
    ('Geopolitics & Public Policy', [
        'CaspianReport', 'Center for Strategic & International Studies',
        'CFR Education', 'Daily Mail World', 'Fair Observer',
        'History of Everything Podcast', 'Hoover Institution', 'Johnny Harris',
        'Max Fisher', 'Max Klymenko', 'MONUSCO', 'neo', 'PolyMatter',
        "Prime Minister's Office of Japan", 'Sundellviz', 'Wendover Productions',
    ]),
    ('News & Current Affairs', [
        'BBC News', 'Bloomberg Originals', 'Business Insider', 'Channel 4 News',
        'CNBC', 'CNN', 'Forbes', 'MS NOW', 'NBC News', 'NPR', 'ReasonTV',
        'The Wall Street Journal', 'TLDR News Global', 'TLDR News US', 'Vox',
        'WIRED',
    ]),
    ('Economics & Business', [
        'Econ', 'Economics Explained', 'How Money Works', 'Kyla Scanlon',
        'Micro', 'Our Future', 'Bloomberg Originals', 'Business Insider',
        'CNBC', 'Forbes', 'The Wall Street Journal',
    ]),
    ('War, Defense & Intelligence', [
        'Battle Order', 'Cappy Army', 'Center for Strategic & International Studies',
        'Front Cost', 'Growling Sidewinder', 'Northrop Grumman',
        'Not What You Think', 'Perun', 'Ryan McBeth', 'Sam Eckholm',
        'The Intel Report', 'WarFronts',
    ]),
    ('Military History', [
        'Bellum et Historia', 'Eastory', 'Kings and Generals', 'Montemayor',
        'The Operations Room', 'World War Two', 'Geo History', 'Epic History',
        'Battle Order', 'The Intel Report',
    ]),
    ('History & Archaeology', [
        'Andrew Lantz', 'Curious Archive', 'Epic History', 'History Documentary',
        'History of Everything Podcast', 'History Scope', 'Knowledgia', 'Madmam',
        'Miniminuteman', 'OverSimplified', 'See U in History / Mythology',
        'Smithsonian Channel', 'stakuyi', 'Today I Learned Science', 'Top5s',
        'World War Two', 'Kings and Generals', 'Eastory', 'Geo History',
    ]),
    ('Geography & Cities', [
        'Geography By Geoff', 'Geography Now', 'Geo History', 'Extremities',
        'Cityburg', 'Johnny Harris', 'neo', 'PolyMatter', 'Wendover Productions',
        'CaspianReport', 'Great Big Story', 'Half as Interesting',
    ]),
    ('Science', [
        'CrashCourse', 'Howtown', 'Insider Science', 'Kurzgesagt – In a Nutshell',
        'MIT OpenCourseWare', 'Nobel Prize', 'PBS Terra', 'Professor Dave Explains',
        'Quanta Magazine', 'Scientific American', 'Seeker', 'Smithsonian Channel',
        'TED-Ed', 'Today I Learned Science', 'Verge Science', 'Veritasium', 'Vsauce',
    ]),
    ('Physics & Astronomy', [
        '3Blue1Brown', 'Dr Ben Miles', 'Epic Spaceman', 'Isaac Arthur',
        'Mathemaniac', 'minutephysics', 'ScienceClic English', 'The Action Lab',
        'Tibees', 'Veritasium', 'Welch Labs', 'Quantum Sense', 'Quanta Magazine',
        'Professor Dave Explains',
    ]),
    ('Mathematics & CS Theory', [
        '2swap', '3Blue1Brown', 'Absolutely Uniformly Confused', 'Aleph 0',
        'Algorithmic Simplicity', 'Chalk Talk', 'EpsilonDelta', 'Mathemaniac',
        'Nemean', 'Polylog', 'Quanta Magazine', 'Quantum Sense',
        'Simons Foundation', 'Spanning Tree', 'Tibees',
    ]),
    ('Chemistry, Biology & Medicine', [
        'Artem Kirsanov', 'AntsCanada', "Dr Hope's Sick Notes", 'Periodic Videos',
        'Professor Dave Explains', 'Reactions', 'Seeker', 'Scientific American',
        'Today I Learned Science', 'BBC Earth', 'PBS Terra',
    ]),
    ('Nature & Climate', [
        '4ocean', 'Andrew Millison', 'AntsCanada', 'BBC Earth', 'Going Green',
        'Mossy Earth', 'PBS Terra', 'Seeker', 'Scientific American',
        'Smithsonian Channel', 'Verge Science',
    ]),
    ('AI & Machine Learning', [
        'Andrej Karpathy', 'Anthropic', 'Artem Kirsanov', 'Arxiv Insights',
        'DeepFindr', 'Deepia', 'Depth First', 'FAR.AI', 'Hod Lipson',
        'ILIAD Conference', 'Jay Alammar', 'Michael Nielsen', 'Mutual Information',
        'Neural Breakdown with AVB', 'Principles of Intelligence',
        'Stanford AI Lab', 'The Alan Turing Institute', 'Yannic Kilcher',
        'Welch Labs', 'Dwarkesh Patel', 'Lex Fridman',
    ]),
    ('Computer Science & Computing', [
        'Algorithmic Simplicity', 'Ben Eater', 'CodeEmporium', 'DeepFindr',
        'Fireship', 'Jabrils', 'Polylog', 'Reducible', 'Sebastian Lague',
        'Spanning Tree', 'TechLinked', 'Qiskit', 'The Alan Turing Institute',
    ]),
    ('Engineering & Infrastructure', [
        'Aaed Musa', 'AiTelly', 'Animagraffs', 'Ben Eater', 'bitluni',
        'BrainfooTV', 'colinfurze', 'DD ElectroTech', 'Engineering Explained',
        'Hacksmith Industries', 'Integza', 'James Bruton', 'Mark Rober',
        'MegaBuilds', 'Practical Engineering', 'Real Engineering',
        'Sabin Civil Engineering', 'Silicon Labs', 'The B1M', 'Will Cogley',
        'Wintergatan',
    ]),
    ('Space, Aviation & Transport', [
        'BPS.shorts', 'Casual Navigation', 'Epic Spaceman', 'flightdeck2sim',
        'Found And Explained', 'Isaac Arthur', 'Mustard', 'Project Da Vinci',
        'Sam Eckholm', 'Space Startup News', 'Understanding Airplanes',
        'Front Cost', 'Northrop Grumman', 'Wendover Productions',
    ]),
    ('Explainers & Philosophy', [
        'Barely Accurate', 'Captain Disillusion', 'Dwarkesh Patel',
        'Great Big Story', 'Half as Interesting', 'LegalBytes', 'LegalEagle',
        'Lex Fridman', 'Max Klymenko', 'Pursuit of Wonder',
        'The Paint Explainer', 'The School of Life', 'Smart Nonsense',
        'CrashCourse', 'TED-Ed',
    ]),
]

# Handles that are NOT simply the name with spaces removed. Everything else
# falls back to that guess, and the resolver confirms or flags it — nothing
# here is trusted until YouTube itself returns a channelId.
HANDLE_OVERRIDES = {
    'Center for Strategic & International Studies': 'csis',
    'Kurzgesagt – In a Nutshell': 'kurzgesagt',
    'See U in History / Mythology': 'SeeUinHistory',
    'The Wall Street Journal': 'WSJ',
    'Prime Minister\'s Office of Japan': 'PMOJapan',
    'Bloomberg Originals': 'bloombergoriginals',
    'MIT OpenCourseWare': 'mitocw',
    'FAR.AI': 'farairesearch',
    'Dr Hope\'s Sick Notes': 'DrHopesSickNotes',
    'BPS.shorts': 'bps.space',
    'TED-Ed': 'TEDEd',
    'Periodic Videos': 'periodicvideos',
    'Quanta Magazine': 'QuantaScienceChannel',
    'Scientific American': 'SciAmerican',
    'National Public Radio': 'NPR',
    'Channel 4 News': 'Channel4News',
    'BBC News': 'BBCNews',
    'BBC Earth': 'bbcearth',
    'Smithsonian Channel': 'SmithsonianChannel',
    'Nobel Prize': 'thenobelprize',
    'Simons Foundation': 'SimonsFoundation',
    'Stanford AI Lab': 'stanfordailab',
    'The Alan Turing Institute': 'TheAlanTuringInstitute',
    'Hoover Institution': 'HooverInstitution',
    'CFR Education': 'CFReducation',
    'Business Insider': 'businessinsider',
    'Insider Science': 'InsiderScience',
    'Verge Science': 'VergeScience',
    'Engineering Explained': 'EngineeringExplained',
    'Practical Engineering': 'PracticalEngineering',
    'Real Engineering': 'RealEngineering',
    'Northrop Grumman': 'northropgrumman',
    'Silicon Labs': 'siliconlabs',
    'The Operations Room': 'TheOperationsRoom',
    'Kings and Generals': 'KingsandGenerals',
    'The Intel Report': 'TheIntelReport',
    'Geography By Geoff': 'GeographyByGeoff',
    'Geography Now': 'GeographyNow',
    'Geo History': 'GeoHistory',
    'Epic History': 'EpicHistoryTV',
    'World War Two': 'WorldWarTwo',
    'History of Everything Podcast': 'TheHistoryofEverything',
    'Great Big Story': 'greatbigstory',
    'Half as Interesting': 'halfasinteresting',
    'Wendover Productions': 'Wendoverproductions',
    'Johnny Harris': 'johnnyharris',
    'Lex Fridman': 'lexfridman',
    'Dwarkesh Patel': 'DwarkeshPatel',
    'Andrej Karpathy': 'AndrejKarpathy',
    'Yannic Kilcher': 'YannicKilcher',
    'Jay Alammar': 'arp1',
    'Michael Nielsen': 'MichaelNielsen',
    'Mutual Information': 'Mutual_Information',
    'Sebastian Lague': 'SebastianLague',
    'Mark Rober': 'MarkRober',
    'James Bruton': 'JamesBruton',
    'The B1M': 'TheB1M',
    'Ryan McBeth': 'RyanMcBethProgramming',
    'Not What You Think': 'NotWhatYouThink',
    'Growling Sidewinder': 'GrowlingSidewinder',
    'Sam Eckholm': 'SamEckholm',
    'Battle Order': 'BattleOrder',
    'Casual Navigation': 'CasualNavigation',
    'Found And Explained': 'FoundAndExplained',
    'Understanding Airplanes': 'UnderstandingAirplanes',
    'Professor Dave Explains': 'ProfessorDaveExplains',
    'The Action Lab': 'TheActionLab',
    'ScienceClic English': 'ScienceClicEN',
    'Welch Labs': 'WelchLabsVideo',
    'Economics Explained': 'EconomicsExplained',
    'How Money Works': 'HowMoneyWorks',
    'Kyla Scanlon': 'kylascanlon',
    'TLDR News Global': 'TLDRNewsGlobal',
    'TLDR News US': 'TLDRnewsUS',
    'Daily Mail World': 'DailyMail',
    'Fair Observer': 'FairObserver',
    'Max Klymenko': 'MaxKlymenko',
    'Max Fisher': 'MaxFisherVideo',
    'Curious Archive': 'CuriousArchive',
    'Andrew Millison': 'amillison',
    'Mossy Earth': 'MossyEarth',
    'Going Green': 'GoingGreen',
    'Captain Disillusion': 'CaptainDisillusion',
    'Pursuit of Wonder': 'PursuitofWonder',
    'The School of Life': 'theschooloflifetv',
    'The Paint Explainer': 'ThePaintExplainer',
    'Neural Breakdown with AVB': 'avb_fj',
    'Principles of Intelligence': 'PrinciplesofIntelligence',
    'ILIAD Conference': 'iliadconference',
    'Arxiv Insights': 'ArxivInsights',
    'Absolutely Uniformly Confused': 'AbsolutelyUniformlyConfused',
    'Algorithmic Simplicity': 'algorithmicsimplicity',
    'Aleph 0': 'Aleph0',
    'Chalk Talk': 'ChalkTalk',
    'Spanning Tree': 'SpanningTree',
    'Quantum Sense': 'quantumsense',
    'Space Startup News': 'SpaceStartupNews',
    'Project Da Vinci': 'ProjectDaVinci',
    'Epic Spaceman': 'EpicSpaceman',
    'Isaac Arthur': 'isaacarthurSFIA',
    'Sabin Civil Engineering': 'SabinCivilEngineering',
    'Hacksmith Industries': 'theHacksmith',
    'DD ElectroTech': 'DDElectroTech',
    'Aaed Musa': 'AaedMusa',
    'Will Cogley': 'WillCogley',
    'Today I Learned Science': 'TodayILearnedScience',
    'Bellum et Historia': 'BellumetHistoria',
    'Miniminuteman': 'miniminuteman773',
    'History Scope': 'HistoryScope',
    'History Documentary': 'HistoryDocumentary',
    'Andrew Lantz': 'AndrewLantz',
    'Cappy Army': 'CappyArmy',
    'Front Cost': 'FrontCost',
    'Depth First': 'DepthFirst',
    'Hod Lipson': 'HodLipson',
    'Dr Ben Miles': 'DrBenMiles',
    'Artem Kirsanov': 'ArtemKirsanov',
    'Our Future': 'OurFuture',
    'Smart Nonsense': 'SmartNonsense',
    'Barely Accurate': 'BarelyAccurate',
    'MS NOW': 'MSNOW',
    'ReasonTV': 'ReasonTV',
    'WarFronts': 'WarFronts',
}

# The site's own subject matter — a channel in one of these topics is much more
# likely to be relevant to a tracked geopolitics story, which link_youtube.py
# uses to break ties. Purely a ranking hint; nothing is excluded by it.
CORE_TOPICS = {
    'Geopolitics & Public Policy', 'News & Current Affairs',
    'Economics & Business', 'War, Defense & Intelligence',
    'Military History', 'Geography & Cities',
}


def guess_handle(name):
    if name in HANDLE_OVERRIDES:
        return HANDLE_OVERRIDES[name]
    # Default guess: the name with everything but letters/digits removed. The
    # resolver verifies it against YouTube; a wrong guess is flagged, not kept.
    return ''.join(ch for ch in name if ch.isalnum())


def main():
    dry_run = '--dry-run' in sys.argv
    rows = load_sources()

    order = []
    entries = {}
    for topic, names in TOPICS:
        for name in names:
            key = name.lower()
            if key not in entries:
                entries[key] = {
                    'name': name,
                    'category': [],
                    'handle': guess_handle(name),
                }
                order.append(key)
            cat = YOUTUBE_PREFIX + topic
            if cat not in entries[key]['category']:
                entries[key]['category'].append(cat)

    existing_ids = {r['source_id'] for r in rows}
    created = updated = 0
    collisions = []
    for key in order:
        e = entries[key]
        sid = 'yt-' + slugify(e['name'])
        # Note (don't merge) a channel that shares a name with a wire outlet.
        if sid not in existing_ids and any(
                (r.get('name') or '').lower() == e['name'].lower() or
                e['name'].lower() in {a.strip().lower()
                                      for a in (r.get('aliases') or '').split(';')}
                for r in rows):
            collisions.append(e['name'])
        row, was_new = upsert({
            'source_id': sid,
            'name': e['name'],
            'category': ';'.join(e['category']),
            'kind': 'youtube',
            'domain': 'youtube.com',
            'handle': e['handle'],
            'alias': e['name'] + ' (YouTube)',
            'scope': 'video',
            # Unverified until pull_youtube.py resolves the handle to a real
            # channel id. Unverified sources are still offered and still tried.
            'status': 'unverified',
            'perspective': 'video',
            'added_by': 'seed-youtube',
            'notes': 'Channel id unresolved — run pull_youtube.py --resolve-channels',
        }, rows)
        created += was_new
        updated += (not was_new)

    print(f'{len(order)} distinct channels across {len(TOPICS)} topics '
          f'({created} new, {updated} already present)')
    if collisions:
        print(f'{len(collisions)} channel(s) share a name with an existing wire '
              f'outlet and were kept SEPARATE (yt- id): ' + ', '.join(collisions))
    multi = [e for e in entries.values() if len(e['category']) > 1]
    print(f'{len(multi)} channels belong to more than one topic, e.g. ' +
          ', '.join(f"{e['name']} ({len(e['category'])})" for e in multi[:5]))

    if dry_run:
        print('Dry run — nothing written.')
        return
    save_sources(rows)
    print(f'Wrote {len(rows)} sources.')
    print('Categories now:')
    for c in all_categories(rows):
        n = sum(1 for r in rows if c in (r.get('category') or '').split(';'))
        print(f'  {n:4d}  {c}')


if __name__ == '__main__':
    main()
