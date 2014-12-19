import unittest
import server
from mock import patch, Mock
import mongomock
from dao import Dao
from scraper.tio import TioScraper
from model import *
import json
import rankings
from bson.objectid import ObjectId
import requests
from datetime import datetime
import facebook

NORCAL_FILES = [('test/data/norcal1.tio', 'Singles'), ('test/data/norcal2.tio', 'Singles Pro Bracket')]
TEXAS_FILES = [('test/data/texas1.tio', 'singles'), ('test/data/texas2.tio', 'singles')]

NORCAL_REGION_NAME = 'norcal'
TEXAS_REGION_NAME = 'texas'

class TestServer(unittest.TestCase):
    def setUp(self):
        self.mongo_client_patcher = patch('server.mongo_client', new=mongomock.MongoClient())
        self.mongo_client = self.mongo_client_patcher.start()

        server.app.config['TESTING'] = True
        self.app = server.app.test_client()

        self.norcal_region = Region('norcal', 'Norcal')
        self.texas_region = Region('texas', 'Texas')
        Dao.insert_region(self.norcal_region, self.mongo_client)
        Dao.insert_region(self.texas_region, self.mongo_client)

        self.norcal_dao = Dao(NORCAL_REGION_NAME, mongo_client=self.mongo_client)
        self.texas_dao = Dao(TEXAS_REGION_NAME, mongo_client=self.mongo_client)

        self._import_files()

        now = datetime(2014, 11, 1)
        rankings.generate_ranking(self.norcal_dao, now=now)
        rankings.generate_ranking(self.texas_dao, now=now)

        self.user_id = 'asdf'
        self.user_full_name = 'full name'
        self.user_admin_regions = ['norcal', 'nyc']
        self.user = User(self.user_id, self.user_admin_regions, full_name=self.user_full_name)
        self.norcal_dao.insert_user(self.user)

    def _import_files(self):
        for f in NORCAL_FILES:
            scraper = TioScraper.from_file(f[0], f[1])
            self._import_players(scraper, self.norcal_dao)
            player_map = self.norcal_dao.get_player_id_map_from_player_aliases(scraper.get_players())
            self.norcal_dao.insert_tournament(Tournament.from_scraper('tio', scraper, player_map, self.norcal_dao.region_id))

        for f in TEXAS_FILES:
            scraper = TioScraper.from_file(f[0], f[1])
            self._import_players(scraper, self.texas_dao)
            player_map = self.texas_dao.get_player_id_map_from_player_aliases(scraper.get_players())
            self.texas_dao.insert_tournament(Tournament.from_scraper('tio', scraper, player_map, self.texas_dao.region_id))

    def _import_players(self, scraper, dao):
        for player in scraper.get_players():
            db_player = dao.get_player_by_alias(player)
            if db_player is None:
                db_player = Player(
                        player, 
                        [player.lower()], 
                        {dao.region_id: TrueskillRating()},
                        [dao.region_id])
                dao.insert_player(db_player)

    def test_get_region_list(self):
        data = self.app.get('/regions').data

        expected_region_dict = {
                'regions': [
                    {'id': 'norcal', 'display_name': 'Norcal'},
                    {'id': 'texas', 'display_name': 'Texas'}
                ]
        }

        self.assertEquals(json.loads(data), expected_region_dict)

    def test_get_player_list(self):
        def for_region(json_data, dao):
            self.assertEquals(json_data.keys(), ['players'])
            players_list = json_data['players']
            players_from_db = dao.get_all_players()
            self.assertEquals(len(players_list), len(players_from_db))

            for player in players_list:
                expected_keys = set(['id', 'name'])
                self.assertEquals(set(player.keys()), expected_keys)
                self.assertEquals(ObjectId(player['id']), dao.get_player_by_alias(player['name']).id)

        data = self.app.get('/norcal/players').data
        json_data = json.loads(data)
        self.assertEquals(len(json_data['players']), 65)
        for_region(json_data, self.norcal_dao)

        data = self.app.get('/texas/players').data
        json_data = json.loads(data)
        self.assertEquals(len(json_data['players']), 41)
        for_region(json_data, self.texas_dao)

    def test_get_player_list_with_alias(self):
        player = self.norcal_dao.get_player_by_alias('gar')

        data = self.app.get('/norcal/players?alias=gar').data
        json_data = json.loads(data)
        self.assertEquals(len(json_data['players']), 1)

        json_player = json_data['players'][0]
        expected_keys = set(['id', 'name'])
        self.assertEquals(set(json_player.keys()), expected_keys)
        self.assertEquals(ObjectId(json_player['id']), player.id)

    def test_get_player_list_case_insensitive(self):
        player = self.norcal_dao.get_player_by_alias('gar')

        data = self.app.get('/norcal/players?alias=GAR').data
        json_data = json.loads(data)
        self.assertEquals(len(json_data['players']), 1)

        json_player = json_data['players'][0]
        expected_keys = set(['id', 'name'])
        self.assertEquals(set(json_player.keys()), expected_keys)
        self.assertEquals(ObjectId(json_player['id']), player.id)

    def test_get_player_list_with_bad_alias(self):
        data = self.app.get('/norcal/players?alias=BADALIAS').data
        json_data = json.loads(data)
        self.assertEquals(len(json_data['players']), 0)

    def test_get_player(self):
        player = self.norcal_dao.get_player_by_alias('gar')
        data = self.app.get('/norcal/players/' + str(player.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['id'], str(player.id))
        self.assertEquals(json_data['name'], 'gar')
        self.assertEquals(json_data['aliases'], ['gar'])
        self.assertEquals(json_data['regions'], ['norcal'])
        self.assertTrue(json_data['ratings']['norcal']['mu'] > 25.9)
        self.assertTrue(json_data['ratings']['norcal']['sigma'] > 3.89)

        player = self.texas_dao.get_player_by_alias('wobbles')
        data = self.app.get('/texas/players/' + str(player.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['id'], str(player.id))
        self.assertEquals(json_data['name'], 'Wobbles')
        self.assertEquals(json_data['aliases'], ['wobbles'])
        self.assertEquals(json_data['regions'], ['texas'])
        self.assertTrue(json_data['ratings']['texas']['mu'] > 44.5)
        self.assertTrue(json_data['ratings']['texas']['sigma'] > 3.53)

    @patch('server.get_user_from_access_token')
    def test_put_player_region(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(player.regions, ['norcal'])

        response = self.app.put('/norcal/players/' + str(player.id) + '/region/nyc')
        json_data = json.loads(response.data)

        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(set(player.regions), set(['norcal', 'nyc']))

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(set(json_data['regions']), set(['norcal', 'nyc']))

    @patch('server.get_user_from_access_token')
    def test_put_player_region_already_exists(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(player.regions, ['norcal'])

        response = self.app.put('/norcal/players/' + str(player.id) + '/region/norcal')
        json_data = json.loads(response.data)

        self.assertEquals(player.regions, ['norcal'])

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['regions'], ['norcal'])

    @patch('server.get_user_from_access_token')
    def test_put_player_region_invalid_permissions(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        response = self.app.put('/norcal/players/' + str(player.id) + '/region/texas')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')

    @patch('server.get_user_from_access_token')
    def test_delete_player_region(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(player.regions, ['norcal'])

        response = self.app.delete('/norcal/players/' + str(player.id) + '/region/norcal')
        json_data = json.loads(response.data)

        player = self.norcal_dao.get_player_by_id(player.id)
        self.assertEquals(player.regions, [])

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['regions'], [])

    @patch('server.get_user_from_access_token')
    def test_delete_player_region_does_not_exist(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(player.regions, ['norcal'])

        response = self.app.delete('/norcal/players/' + str(player.id) + '/region/nyc')
        json_data = json.loads(response.data)

        player = self.norcal_dao.get_player_by_alias('gar')
        self.assertEquals(player.regions, ['norcal'])

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['regions'], ['norcal'])

    @patch('server.get_user_from_access_token')
    def test_delete_player_region_invalid_permissions(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        player = self.norcal_dao.get_player_by_alias('gar')
        response = self.app.delete('/norcal/players/' + str(player.id) + '/region/texas')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')

    def test_get_tournament_list(self):
        def for_region(data, dao):
            json_data = json.loads(data)

            self.assertEquals(json_data.keys(), ['tournaments'])
            tournaments_list = json_data['tournaments']
            tournaments_from_db = dao.get_all_tournaments(regions=[dao.region_id])
            self.assertEquals(len(tournaments_list), len(tournaments_from_db))

            for tournament in tournaments_list:
                tournament_from_db = dao.get_tournament_by_id(ObjectId(tournament['id']))
                expected_keys = set(['id', 'name', 'date', 'regions'])
                self.assertEquals(set(tournament.keys()), expected_keys)
                self.assertEquals(tournament['id'], str(tournament_from_db.id))
                self.assertEquals(tournament['name'], tournament_from_db.name)
                self.assertEquals(tournament['date'], tournament_from_db.date.strftime('%x'))
                self.assertEquals(tournament['regions'], [dao.region_id])

        data = self.app.get('/norcal/tournaments').data
        for_region(data, self.norcal_dao)

        data = self.app.get('/texas/tournaments').data
        for_region(data, self.texas_dao)

    def test_get_tournament(self):
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        data = self.app.get('/norcal/tournaments/' + str(tournament.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(json_data['id'], str(tournament.id))
        self.assertEquals(json_data['name'], 'BAM: 4 stocks is not a lead')
        self.assertEquals(json_data['type'], 'tio')
        self.assertEquals(json_data['date'], tournament.date.strftime('%x'))
        self.assertEquals(json_data['regions'], ['norcal'])
        self.assertEquals(len(json_data['players']), len(tournament.players))
        self.assertEquals(len(json_data['matches']), len(tournament.matches))

        for player in json_data['players']:
            db_player = self.norcal_dao.get_player_by_id(ObjectId(player['id']))
            self.assertEquals(len(player.keys()), 2)
            self.assertEquals(player['id'], str(db_player.id))
            self.assertEquals(player['name'], db_player.name)

        # spot check first and last match
        match = json_data['matches'][0]
        db_match = tournament.matches[0]
        self.assertEquals(len(match.keys()), 4)
        self.assertEquals(match['winner_id'], str(db_match.winner))
        self.assertEquals(match['winner_name'], self.norcal_dao.get_player_by_id(ObjectId(match['winner_id'])).name)
        self.assertEquals(match['loser_id'], str(db_match.loser))
        self.assertEquals(match['loser_name'], self.norcal_dao.get_player_by_id(ObjectId(match['loser_id'])).name)
        match = json_data['matches'][-1]
        db_match = tournament.matches[-1]
        self.assertEquals(len(match.keys()), 4)
        self.assertEquals(match['winner_id'], str(db_match.winner))
        self.assertEquals(match['winner_name'], self.norcal_dao.get_player_by_id(ObjectId(match['winner_id'])).name)
        self.assertEquals(match['loser_id'], str(db_match.loser))
        self.assertEquals(match['loser_name'], self.norcal_dao.get_player_by_id(ObjectId(match['loser_id'])).name)

        # sanity tests for another region
        tournament = self.texas_dao.get_all_tournaments()[0]
        data = self.app.get('/texas/tournaments/' + str(tournament.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(json_data['id'], str(tournament.id))
        self.assertEquals(json_data['name'], 'FX Biweekly 6')
        self.assertEquals(json_data['type'], 'tio')
        self.assertEquals(json_data['date'], tournament.date.strftime('%x'))
        self.assertEquals(json_data['regions'], ['texas'])
        self.assertEquals(len(json_data['players']), len(tournament.players))
        self.assertEquals(len(json_data['matches']), len(tournament.matches))

    @patch('server.get_user_from_access_token')
    def test_put_tournament_region(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(tournament.regions, ['norcal'])

        response = self.app.put('/norcal/tournaments/' + str(tournament.id) + '/region/nyc')
        json_data = json.loads(response.data)

        tournament = self.norcal_dao.get_tournament_by_id(tournament.id)
        self.assertEquals(set(tournament.regions), set(['norcal', 'nyc']))

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(set(json_data['regions']), set(['norcal', 'nyc']))

    @patch('server.get_user_from_access_token')
    def test_put_tournament_region_already_exists(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(tournament.regions, ['norcal'])

        response = self.app.put('/norcal/tournaments/' + str(tournament.id) + '/region/norcal')
        json_data = json.loads(response.data)

        self.assertEquals(tournament.regions, ['norcal'])

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(json_data['regions'], ['norcal'])

    @patch('server.get_user_from_access_token')
    def test_put_tournament_region_invalid_permissions(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        response = self.app.put('/norcal/tournaments/' + str(tournament.id) + '/region/texas')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')

    @patch('server.get_user_from_access_token')
    def test_delete_tournament_region(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(tournament.regions, ['norcal'])

        response = self.app.delete('/norcal/tournaments/' + str(tournament.id) + '/region/norcal')
        json_data = json.loads(response.data)

        tournament = self.norcal_dao.get_tournament_by_id(tournament.id)
        self.assertEquals(tournament.regions, [])

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(json_data['regions'], [])

    @patch('server.get_user_from_access_token')
    def test_delete_tournament_region_does_not_exist(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(tournament.regions, ['norcal'])

        response = self.app.delete('/norcal/tournaments/' + str(tournament.id) + '/region/nyc')
        json_data = json.loads(response.data)

        tournament = self.norcal_dao.get_tournament_by_id(tournament.id)
        self.assertEquals(tournament.regions, ['norcal'])

        self.assertEquals(len(json_data.keys()), 7)
        self.assertEquals(json_data['regions'], ['norcal'])

    @patch('server.get_user_from_access_token')
    def test_delete_tournament_region_invalid_permissions(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        response = self.app.delete('/norcal/tournaments/' + str(tournament.id) + '/region/texas')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')

    def test_get_rankings(self):
        data = self.app.get('/norcal/rankings').data
        json_data = json.loads(data)
        db_ranking = self.norcal_dao.get_latest_ranking()

        self.assertEquals(len(json_data.keys()), 4)
        self.assertEquals(json_data['time'], str(db_ranking.time))
        self.assertEquals(json_data['tournaments'], [str(t) for t in db_ranking.tournaments])
        self.assertEquals(json_data['region'], self.norcal_dao.region_id)
        self.assertEquals(len(json_data['ranking']), len(db_ranking.ranking))

        # spot check first and last ranking entries
        ranking_entry = json_data['ranking'][0]
        db_ranking_entry = db_ranking.ranking[0]
        self.assertEquals(len(ranking_entry.keys()), 4)
        self.assertEquals(ranking_entry['rank'], db_ranking_entry.rank)
        self.assertEquals(ranking_entry['id'], str(db_ranking_entry.player))
        self.assertEquals(ranking_entry['name'], self.norcal_dao.get_player_by_id(db_ranking_entry.player).name)
        self.assertTrue(ranking_entry['rating'] > 33.2)
        ranking_entry = json_data['ranking'][-1]
        db_ranking_entry = db_ranking.ranking[-1]
        self.assertEquals(len(ranking_entry.keys()), 4)
        self.assertEquals(ranking_entry['rank'], db_ranking_entry.rank)
        self.assertEquals(ranking_entry['id'], str(db_ranking_entry.player))
        self.assertEquals(ranking_entry['name'], self.norcal_dao.get_player_by_id(db_ranking_entry.player).name)
        self.assertTrue(ranking_entry['rating'] > -3.86)

    def test_get_rankings_ignore_invalid_player_id(self):
        # delete a player that exists in the rankings
        db_ranking = self.norcal_dao.get_latest_ranking()
        player_to_delete = self.norcal_dao.get_player_by_id(db_ranking.ranking[1].player)
        self.norcal_dao.delete_player(player_to_delete)

        data = self.app.get('/norcal/rankings').data
        json_data = json.loads(data)
        db_ranking = self.norcal_dao.get_latest_ranking()

        self.assertEquals(len(json_data.keys()), 4)
        self.assertEquals(json_data['time'], str(db_ranking.time))
        self.assertEquals(json_data['tournaments'], [str(t) for t in db_ranking.tournaments])
        self.assertEquals(json_data['region'], self.norcal_dao.region_id)

        # subtract 1 for the player we removed
        self.assertEquals(len(json_data['ranking']), len(db_ranking.ranking) - 1)

        # spot check first and last ranking entries
        ranking_entry = json_data['ranking'][0]
        db_ranking_entry = db_ranking.ranking[0]
        self.assertEquals(len(ranking_entry.keys()), 4)
        self.assertEquals(ranking_entry['rank'], db_ranking_entry.rank)
        self.assertEquals(ranking_entry['id'], str(db_ranking_entry.player))
        self.assertEquals(ranking_entry['name'], self.norcal_dao.get_player_by_id(db_ranking_entry.player).name)
        self.assertTrue(ranking_entry['rating'] > 33.2)

        ranking_entry = json_data['ranking'][-1]
        db_ranking_entry = db_ranking.ranking[-1]
        self.assertEquals(len(ranking_entry.keys()), 4)
        self.assertEquals(ranking_entry['rank'], db_ranking_entry.rank)
        self.assertEquals(ranking_entry['id'], str(db_ranking_entry.player))
        self.assertEquals(ranking_entry['name'], self.norcal_dao.get_player_by_id(db_ranking_entry.player).name)
        self.assertTrue(ranking_entry['rating'] > -3.86)

    def test_get_matches(self):
        player = self.norcal_dao.get_player_by_alias('gar')
        data = self.app.get('/norcal/matches/' + str(player.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 4)

        self.assertEquals(len(json_data['player'].keys()), 2)
        self.assertEquals(json_data['player']['id'], str(player.id))
        self.assertEquals(json_data['player']['name'], player.name)
        self.assertEquals(json_data['wins'], 3)
        self.assertEquals(json_data['losses'], 4)

        matches = json_data['matches']
        self.assertEquals(len(matches), 7)

        # spot check a few matches
        match = matches[0]
        opponent = self.norcal_dao.get_player_by_alias('darrell')
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(len(match.keys()), 6)
        self.assertEquals(match['opponent_id'], str(opponent.id))
        self.assertEquals(match['opponent_name'], opponent.name)
        self.assertEquals(match['result'], 'lose')
        self.assertEquals(match['tournament_id'], str(tournament.id))
        self.assertEquals(match['tournament_name'], tournament.name)
        self.assertEquals(match['tournament_date'], tournament.date.strftime("%x"))

        match = matches[2]
        opponent = self.norcal_dao.get_player_by_alias('eric')
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[1]
        self.assertEquals(len(match.keys()), 6)
        self.assertEquals(match['opponent_id'], str(opponent.id))
        self.assertEquals(match['opponent_name'], opponent.name)
        self.assertEquals(match['result'], 'win')
        self.assertEquals(match['tournament_id'], str(tournament.id))
        self.assertEquals(match['tournament_name'], tournament.name)
        self.assertEquals(match['tournament_date'], tournament.date.strftime("%x"))

    def test_get_matches_with_opponent(self):
        player = self.norcal_dao.get_player_by_alias('gar')
        opponent = self.norcal_dao.get_player_by_alias('tang')
        data = self.app.get('/norcal/matches/' + str(player.id) + "?opponent=" + str(opponent.id)).data
        json_data = json.loads(data)

        self.assertEquals(len(json_data.keys()), 5)
        self.assertEquals(json_data['wins'], 0)
        self.assertEquals(json_data['losses'], 1)

        self.assertEquals(len(json_data['player'].keys()), 2)
        self.assertEquals(json_data['player']['id'], str(player.id))
        self.assertEquals(json_data['player']['name'], player.name)

        self.assertEquals(len(json_data['opponent'].keys()), 2)
        self.assertEquals(json_data['opponent']['id'], str(opponent.id))
        self.assertEquals(json_data['opponent']['name'], opponent.name)

        matches = json_data['matches']
        self.assertEquals(len(matches), 1)

        match = matches[0]
        tournament = self.norcal_dao.get_all_tournaments(regions=['norcal'])[0]
        self.assertEquals(len(match.keys()), 6)
        self.assertEquals(match['opponent_id'], str(opponent.id))
        self.assertEquals(match['opponent_name'], opponent.name)
        self.assertEquals(match['result'], 'lose')
        self.assertEquals(match['tournament_id'], str(tournament.id))
        self.assertEquals(match['tournament_name'], tournament.name)
        self.assertEquals(match['tournament_date'], tournament.date.strftime("%x"))

    @patch('server.requests', spec=requests)
    def test_get_user_from_access_token(self, mock_requests):
        user_id = 'asdf'
        user_full_name = 'full name'
        user = User(user_id, ['norcal'], full_name=user_full_name)
        auth_header = 'auth'

        mock_response = Mock(spec=requests.Response)
        mock_response.json.return_value = {
            'data': {
                'app_id': server.config.get_fb_app_id(),
                'is_valid': True,
                'user_id': user_id
            }
        }

        mock_requests.get.return_value = mock_response

        mock_dao = Mock(spec=Dao)
        mock_dao.get_or_create_user_by_id.return_value = user
        
        retrieved_user = server.get_user_from_access_token({'Authorization': auth_header}, mock_dao)
        self.assertEquals(retrieved_user.id, user.id)
        self.assertEquals(retrieved_user.full_name, user_full_name)
        self.assertEquals(retrieved_user.admin_regions, user.admin_regions)

        expected_url = server.DEBUG_TOKEN_URL % (auth_header, server.config.get_fb_app_token())
        mock_requests.get.assert_called_once_with(expected_url)

        mock_dao.get_or_create_user_by_id.assert_called_once_with(user_id)

    @patch('server.requests', spec=requests)
    @patch('server.facebook', spec=facebook)
    def test_get_user_from_access_token_populate_user_full_name(self, mock_facebook, mock_requests):
        user_id = 'asdf'
        user_full_name = 'full name'
        user = User(user_id, ['norcal'])
        auth_header = 'auth'

        mock_response = Mock(spec=requests.Response)
        mock_response.json.return_value = {
            'data': {
                'app_id': server.config.get_fb_app_id(),
                'is_valid': True,
                'user_id': user_id
            }
        }

        mock_requests.get.return_value = mock_response

        mock_dao = Mock(spec=Dao)
        mock_dao.get_or_create_user_by_id.return_value = user

        mock_graph_api = Mock(spec=facebook.GraphAPI)
        mock_facebook.GraphAPI.return_value = mock_graph_api
        mock_graph_api.get_object.return_value = {'name': user_full_name}
        
        retrieved_user = server.get_user_from_access_token({'Authorization': auth_header}, mock_dao)
        self.assertEquals(retrieved_user.id, user.id)
        self.assertEquals(retrieved_user.full_name, user_full_name)
        self.assertEquals(retrieved_user.admin_regions, user.admin_regions)

        expected_url = server.DEBUG_TOKEN_URL % (auth_header, server.config.get_fb_app_token())
        mock_requests.get.assert_called_once_with(expected_url)

        mock_dao.get_or_create_user_by_id.assert_called_once_with(user_id)
        mock_dao.update_user.assert_called_once_with(user)
        mock_facebook.GraphAPI.assert_called_once_with(auth_header)
        mock_graph_api.get_object.assert_called_once_with('me')

    @patch('server.requests', spec=requests)
    def test_get_user_from_access_token_invalid_app_id(self, mock_requests):
        user_id = 'asdf'
        auth_header = 'auth'

        mock_response = Mock(spec=requests.Response)
        mock_response.json.return_value = {
            'data': {
                'app_id': 'bad app id',
                'is_valid': True,
            }
        }

        mock_requests.get.return_value = mock_response

        with self.assertRaises(server.InvalidAccessToken):
            server.get_user_from_access_token({'Authorization': auth_header}, None)

        expected_url = server.DEBUG_TOKEN_URL % (auth_header, server.config.get_fb_app_token())
        mock_requests.get.assert_called_once_with(expected_url)

    @patch('server.requests', spec=requests)
    def test_get_user_from_access_token_invalid_response(self, mock_requests):
        user_id = 'asdf'
        auth_header = 'auth'

        mock_response = Mock(spec=requests.Response)
        mock_response.json.return_value = {
            'data': {
                'app_id': server.config.get_fb_app_id(),
                'is_valid': False
            }
        }

        mock_requests.get.return_value = mock_response

        with self.assertRaises(server.InvalidAccessToken):
            server.get_user_from_access_token({'Authorization': auth_header}, None)

        expected_url = server.DEBUG_TOKEN_URL % (auth_header, server.config.get_fb_app_token())
        mock_requests.get.assert_called_once_with(expected_url)

    @patch('server.get_user_from_access_token')
    def test_get_current_user(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        data = self.app.get('/users/me').data
        json_data = json.loads(data)

        expected_data = {
                'id': self.user_id,
                'full_name': self.user_full_name,
                'admin_regions': self.user_admin_regions
        }

        self.assertEquals(json_data, expected_data)

    @patch('server.get_user_from_access_token')
    def test_put_tournament_name_change(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]

        #save info about it
        tourney_id = the_tourney.id
        old_date = the_tourney.date
        old_matches = the_tourney.matches
        old_players = the_tourney.players
        old_raw = the_tourney.raw
        old_regions = the_tourney.regions
        old_type = the_tourney.type

        #construct info for first test
        new_tourney_name = "jessesGodlikeTourney"
        raw_dict = {'name': new_tourney_name}
        test_data = json.dumps(raw_dict)

        #try overwriting an existing tournament and changing just its name, make sure all the other attributes are fine
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK')
        the_tourney = dao.get_tournament_by_id(tourney_id)
        self.assertEquals(the_tourney.name, new_tourney_name)
        self.assertEquals(old_date, the_tourney.date)
        self.assertEquals(old_matches, the_tourney.matches)
        self.assertEquals(old_players, the_tourney.players)
        self.assertEquals(old_raw, the_tourney.raw)
        self.assertEquals(old_regions, the_tourney.regions)
        self.assertEquals(old_type, the_tourney.type)

    @patch('server.get_user_from_access_token')
    def test_put_tournament_everything_change(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]

        #save info about it
        tourney_id = the_tourney.id
        new_tourney_name = "jessesGodlikeTourney"
        old_raw = the_tourney.raw
        old_type = the_tourney.type
        #setup for test 2
        player1 = ObjectId()
        player2 = ObjectId()
        new_players = (player1, player2)
        new_matches = (MatchResult(player1, player2), MatchResult(player2, player1))

        new_matches_for_wire = ({'winner': str(player1), 'loser': str(player2) }, {'winner': str(player2), 'loser': str(player1)})
        new_date = datetime.now()
        new_regions = ("norcal", "socal")
        raw_dict = {'name': new_tourney_name, 'date': new_date.toordinal(), 'matches': new_matches_for_wire, 'regions': new_regions, 'players': [str(p) for p in new_players]}
        test_data = json.dumps(raw_dict)

        # try overwriting all its writeable attributes: date players matches regions
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK')
        the_tourney = dao.get_tournament_by_id(tourney_id)
        self.assertEquals(the_tourney.name, new_tourney_name)
        self.assertEquals(new_date.toordinal(), the_tourney.date.toordinal())
        for m1,m2 in zip(new_matches, the_tourney.matches):
            self.assertEqual(m1.winner, m2.winner)
            self.assertEqual(m1.loser, m2.loser)

        self.assertEquals(set(new_players), set(the_tourney.players))
        self.assertEquals(old_raw, the_tourney.raw)
        self.assertEquals(set(new_regions), set(the_tourney.regions))
        self.assertEquals(old_type, the_tourney.type)

    def test_put_tournament_invalid_id(self):
        #construct info
        new_tourney_name = "jessesGodlikeTourney"
        raw_dict = {'name': new_tourney_name}
        test_data = json.dumps(raw_dict)
        # try sending one with an invalid tourney ID
        rv = self.app.put('/norcal/tournaments/' + str(ObjectId()), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_player_name(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #non string player name
        raw_dict = {'players': ("abc", 123)}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_winner(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #match with numerical winner
        raw_dict = {'matches': {'winner': 123, 'loser': 'bob'}}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_types_loser(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #match with numerical loser
        raw_dict = {'matches': {'winner': 'bob', 'loser': 123}}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_types_both(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #match with both numerical
        raw_dict = {'matches': {'winner': 1234, 'loser': 123}}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_region(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #match with both numerical
        raw_dict = {'regions': ("abc", 123)}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_invalid_matches(self, mock_get_user_from_access_token):
        #initial setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        #pick a tournament
        tournaments_from_db = dao.get_all_tournaments(regions=['norcal'])
        the_tourney = tournaments_from_db[0]
        #save info about it
        tourney_id = the_tourney.id
        #match with both numerical
        raw_dict = {'matches': 123}
        test_data = json.dumps(raw_dict)
        rv = self.app.put('/norcal/tournaments/' + str(tourney_id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_tournament_permission_denied(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        dao = self.texas_dao
        tournaments_from_db = dao.get_all_tournaments(regions=['texas'])
        the_tourney = tournaments_from_db[0]
        response = self.app.put('/texas/tournaments/' + str(the_tourney.id), content_type='application/json')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')

    @patch('server.get_user_from_access_token')
    def test_put_player_update_name(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]
        player_id = the_player.id
        old_regions = the_player.regions
        old_aliases = the_player.aliases
        old_ratings = the_player.ratings

        #construct info for first test
        new_name = 'someone'
        raw_dict = {'name': new_name}
        test_data = json.dumps(raw_dict)

        #test updating name
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK')
        the_player = dao.get_player_by_id(player_id)
        self.assertEqual(the_player.ratings, old_ratings)
        self.assertEqual(set(the_player.aliases), set(old_aliases))
        self.assertEqual(set(the_player.regions), set(old_regions))
        self.assertEqual(the_player.name, new_name)

    @patch('server.get_user_from_access_token')
    def test_put_player_update_aliases(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]
        player_id = the_player.id
        old_regions = the_player.regions
        old_ratings = the_player.ratings

        #first, change their name
        new_name = 'someone'
        raw_dict = {'name': new_name}
        test_data = json.dumps(raw_dict)

        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK')

        #construct info for second test
        new_aliases = ('someone', 'someoneelse', 'unknowndude')
        raw_dict = {'aliases': new_aliases}
        test_data = json.dumps(raw_dict)

        #test updating aliases
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK', msg=rv.data)
        the_player = dao.get_player_by_id(player_id)
        self.assertEqual(set(the_player.aliases), set(new_aliases))
        self.assertEqual(the_player.ratings, old_ratings)
        self.assertEqual(set(the_player.regions), set(old_regions))

    @patch('server.get_user_from_access_token')
    def test_put_player_invalid_aliases(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]

        #construct info for third test
        new_aliases = ('nope', 'someoneelse', 'unknowndude')
        raw_dict = {'aliases': new_aliases}
        test_data = json.dumps(raw_dict)

        #test updating aliases with invalid aliases list
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_player_update_regions(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]
        player_id = the_player.id
        old_ratings = the_player.ratings

        #construct info for fourth test
        new_regions = ('norcal', 'nyc')
        raw_dict = {'regions': new_regions}
        test_data = json.dumps(raw_dict)

        #test updating regions
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEqual(rv.status, '200 OK', msg=rv.data)
        the_player = dao.get_player_by_id(player_id)
        self.assertEqual(the_player.ratings, old_ratings)
        self.assertEqual(set(the_player.regions), set(new_regions))

    def test_put_player_not_found(self):
        #construct info for test
        new_regions = ('norcal', 'nyc')
        raw_dict = {'regions': new_regions}
        test_data = json.dumps(raw_dict)
        #test player not found
        rv = self.app.put('/norcal/players/' + str(ObjectId()), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_player_nonstring_aliases(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]
        #construct info for test
        raw_dict = {'aliases': ('abc', 123)}
        test_data = json.dumps(raw_dict)

        #test updating regions
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_player_nonstring_regions(self, mock_get_user_from_access_token):
        #setup
        mock_get_user_from_access_token.return_value = self.user
        dao = self.norcal_dao
        players = dao.get_all_players()
        the_player = players[0]
        player_id = the_player.id
        #construct info for test
        aliases = ('norcal', 'nyc')
        raw_dict = {'aliases': ('abc', 123)}
        test_data = json.dumps(raw_dict)

        #test updating regions
        rv = self.app.put('/norcal/players/' + str(the_player.id), data=test_data, content_type='application/json')
        self.assertEquals(rv.status, '400 BAD REQUEST')

    @patch('server.get_user_from_access_token')
    def test_put_player_permission_denied(self, mock_get_user_from_access_token):
        mock_get_user_from_access_token.return_value = self.user
        dao = self.texas_dao
        players = dao.get_all_players()
        the_player = players[0]
        response = self.app.put('/texas/players/' + str(the_player.id), content_type='application/json')
        self.assertEquals(response.status_code, 403)
        self.assertEquals(response.data, '"Permission denied"')
