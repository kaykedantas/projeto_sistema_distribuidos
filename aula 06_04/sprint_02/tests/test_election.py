from src.election import elect_master

def test_elect_master_lexicographic():
    replies = [
        {"MASTER_NAME":"MASTER_2","MASTER_IP":"10.0.0.2"},
        {"MASTER_NAME":"MASTER_1","MASTER_IP":"10.0.0.1"},
    ]
    winner = elect_master(replies)
    assert winner['MASTER_NAME'] == 'MASTER_1'
