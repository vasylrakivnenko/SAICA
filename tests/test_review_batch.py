from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_batch.py"


def git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


class ReviewBatchTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))
        git(self.repo, "init", "-q")
        (self.repo / ".gitignore").write_text(".saica/\n")
        (self.repo / "scoped.txt").write_text("committed\n")
        (self.repo / "outside.txt").write_text("untouched\n")
        git(self.repo, "add", ".")
        git(
            self.repo,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "base",
        )

    def batch(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=self.repo, capture_output=True
        )

    def output(self, *args):
        result = self.batch(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.decode().strip()

    def assert_refused(self, message, *args):
        result = self.batch(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_frozen_patch_applies_exactly_and_stale_checkout_is_rejected(self):
        (self.repo / "scoped.txt").write_text("local edit excluded\n")
        run = Path(self.output("prepare", "scoped.txt", "new.bin"))
        checkout = run / "edit"
        self.assertEqual((checkout / "scoped.txt").read_text(), "committed\n")
        self.assertEqual(git(checkout, "remote"), "")
        (checkout / "scoped.txt").write_text("Claude change\n")
        binary = b"\x00\xff"
        (checkout / "new.bin").write_bytes(binary)
        self.assert_refused(b"Untracked", "capture", run)
        git(checkout, "add", "-N", "--", "new.bin")
        review = Path(self.output("capture", run))
        patch = review / "candidate.patch"
        self.assertEqual(patch.stat().st_mode & 0o777, 0o400)
        self.assertEqual(
            self.output("verify", review).split()[0],
            git(self.repo, "rev-parse", "HEAD"),
        )
        self.assertEqual(
            (self.repo / "scoped.txt").read_text(), "local edit excluded\n"
        )
        git(self.repo, "restore", "scoped.txt")
        git(self.repo, "apply", "--check", str(patch))
        git(self.repo, "apply", str(patch))
        self.assertEqual((self.repo / "scoped.txt").read_text(), "Claude change\n")
        self.assertEqual((self.repo / "new.bin").read_bytes(), binary)
        (checkout / "scoped.txt").write_text("different candidate\n")
        self.assert_refused(b"differs", "verify", review)

    def test_scope_and_empty_patch_are_rejected(self):
        run = Path(self.output("prepare", "scoped.txt"))
        self.assert_refused(b"No changes", "capture", run)
        (run / "edit" / "outside.txt").unlink()
        self.assert_refused(b"outside.txt", "capture", run)
        self.assertEqual(list(run.glob("review-*")), [])

    def test_tampered_patch_is_rejected(self):
        run = Path(self.output("prepare", "scoped.txt"))
        (run / "edit" / "scoped.txt").write_text("changed\n")
        review = Path(self.output("capture", run))
        patch = review / "candidate.patch"
        patch.chmod(0o600)
        patch.write_bytes(b"tampered")
        self.assert_refused(b"SHA-256", "verify", review)

    def test_inline_input_is_exact_and_rejects_oversized_or_unsafe_patches(self):
        run = Path(self.output("prepare", "scoped.txt"))
        edited = run / "edit" / "scoped.txt"
        edited.write_text("edited é\t \n\n", encoding="utf-8")
        review = Path(self.output("capture", run))
        prompt = self.batch("prompt", review)
        self.assertEqual(prompt.returncode, 0, prompt.stderr)
        begin, end = b"<<< BEGIN PATCH >>>\n", b"<<< END PATCH >>>\n"
        self.assertTrue(prompt.stdout.endswith(end))
        self.assertEqual(
            prompt.stdout.split(begin, 1)[1].removesuffix(end),
            (review / "candidate.patch").read_bytes(),
        )
        edited.write_text("a" * 8001)
        self.assert_refused(b"too large", "prompt", self.output("capture", run))
        edited.write_bytes(b"edited \x1b\n")
        self.assert_refused(b"terminal control", "prompt", self.output("capture", run))
