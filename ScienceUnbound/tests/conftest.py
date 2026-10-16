import warnings

import pytest

warnings.filterwarnings("ignore")


@pytest.fixture(scope="session")
def demo_raw():
    from scienceunbound.demo import make_demo
    from scienceunbound.ingest import normalize
    return normalize(make_demo())


@pytest.fixture(scope="session")
def demo_clean(demo_raw):
    from scienceunbound.privacy import audit_dataframe
    return demo_raw.drop(columns=audit_dataframe(demo_raw).to_drop())


@pytest.fixture(scope="session")
def demo_plan():
    from scienceunbound.demo import demo_plan
    return demo_plan()


@pytest.fixture(scope="session")
def demo_lock(demo_plan):
    from scienceunbound.registration import make_lock
    return make_lock(demo_plan, when="2026-03-01T10:00:00Z")


@pytest.fixture(scope="session")
def demo_result(demo_clean, demo_plan, demo_lock):
    from scienceunbound.analyze import run_analysis
    return run_analysis(demo_clean, demo_plan, demo_lock)


@pytest.fixture(scope="session")
def demo_package(demo_result, demo_clean, demo_lock):
    from scienceunbound.package import build_package
    return build_package(demo_result, lock=demo_lock, priv={"dropped": ["ResponseId"], "k_stats": {}, "k_actions": None},
                         include_data=True, df_input=demo_clean, repo_url="https://github.com/eugendimant/ScienceUnbound",
                         generated_on="2026-10-16")
