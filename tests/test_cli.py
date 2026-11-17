from argumentum.cli import build_parser


def test_run_parser_accepts_full_workflow_harness():
    args = build_parser().parse_args(
        [
            "run",
            "--topic",
            "A topic",
            "--question",
            "A sufficiently detailed research question",
            "--harness",
            "native",
            "--demo",
        ]
    )
    assert args.harness == "native" and args.demo
