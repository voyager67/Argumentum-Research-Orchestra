import pytest
from argumentum.evaluation import score_retrieval_query

def test_perfect_ranking_scores_one():
    result=score_retrieval_query(["a","b"],["a","b"],2)
    assert result["precision@2"]==1 and result["recall@2"]==1 and result["ndcg@2"]==1

def test_no_retrieval_has_zero_hit_rate():
    assert score_retrieval_query([], ["gold"], 5)["hit_rate@5"]==0

def test_duplicate_retrieved_ids_are_rejected():
    with pytest.raises(ValueError):score_retrieval_query(["a","a"],["a"],2)
