== synced : submodule checked out at the recorded commit ==
OK — 1 submodule(s) in sync.

== super : after the submodule moved on ==
FAIL libs/sub: checked-out HEAD e34ce797ad9ea3e012331d2d1702097e74f894f8 differs from recorded commit c41a7332fb48964056eaa00099ba037e48d07965
Checked 1 repo(s), 1 problem(s) in 1 repo(s).

== clone : fresh clone, submodule never initialised ==
FAIL libs/sub: uninitialised — recorded commit c41a7332fb48964056eaa00099ba037e48d07965, no checkout found
Checked 1 repo(s), 1 problem(s) in 1 repo(s).

== super --json : the drifted repo as JSON ==
{
  "repos": [
    {
      "path": "super",
      "submodules": [
        {
          "path": "libs/sub",
          "recorded": "c41a7332fb48964056eaa00099ba037e48d07965",
          "head": "e34ce797ad9ea3e012331d2d1702097e74f894f8",
          "status": "drifted",
          "message": "checked-out HEAD e34ce797ad9ea3e012331d2d1702097e74f894f8 differs from recorded commit c41a7332fb48964056eaa00099ba037e48d07965"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "problems": 1
}
