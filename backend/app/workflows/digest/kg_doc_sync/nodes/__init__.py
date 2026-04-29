"""Knowledge-doc sync graph node modules.

Read these node files in graph order to understand the whole lane:

1. ``prepare`` validates course, markdown and DocGen structured context.
2. ``init_run`` opens one DB-backed sync run and resolves the target graph revision.
3. ``extract`` fans out the published knowledge doc into section LLM extraction tasks.
4. ``persist`` merges extracted candidates into knowledge_unit / knowledge_edge tables.
5. ``finalize`` returns the compact report consumed by build runtime.
6. ``fail`` marks the sync run failed when an earlier node cannot continue.

Import node functions from their concrete modules to keep graph dependencies explicit.
"""

__all__: list[str] = []
