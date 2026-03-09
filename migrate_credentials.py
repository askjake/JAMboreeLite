#!/usr/bin/env python3
"""
JAMboreeLite Credential Migration Script

This script migrates STB credentials from plaintext storage in base.txt
to secure OS keyring storage.

Features:
- Verification mode: preview what will be migrated
- Safe mode: backup base.txt before making changes
- Option to remove plaintext credentials after migration
- Detailed reporting of migration results

Usage:
    # Verification only (dry run)
    python migrate_credentials.py --verify

    # Migrate to keyring, keep plaintext in base.txt (safe)
    python migrate_credentials.py
    
    # Migrate and remove plaintext from base.txt (recommended after verification)
    python migrate_credentials.py --remove-plaintext
    
    # Specify custom base.txt location
    python migrate_credentials.py --base-file /path/to/base.txt
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Tuple

# Add jamboree to path
sys.path.insert(0, str(Path(__file__).parent))

from jamboree.core.credentials import CredentialManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class CredentialMigrator:
    """Handles migration of credentials from base.txt to keyring."""
    
    def __init__(self, base_file: Path):
        self.base_file = base_file
        self.backup_file = base_file.with_suffix('.txt.backup')
        self.base_data = None
    
    def load_base_file(self) -> bool:
        """Load base.txt file."""
        if not self.base_file.exists():
            logger.error(f"Base file not found: {self.base_file}")
            return False
        
        try:
            with open(self.base_file, 'r', encoding='utf-8') as f:
                self.base_data = json.load(f)
            logger.info(f"Loaded base file: {self.base_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to load base file: {e}")
            return False
    
    def backup_base_file(self) -> bool:
        """Create backup of base.txt."""
        try:
            import shutil
            shutil.copy2(self.base_file, self.backup_file)
            logger.info(f"Created backup: {self.backup_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return False
    
    def scan_credentials(self) -> Tuple[List[Dict], List[str]]:
        """
        Scan base.txt for credentials.
        
        Returns:
            Tuple of (stbs_with_creds, stbs_without_creds)
        """
        stbs_with_creds = []
        stbs_without_creds = []
        
        if not self.base_data:
            return stbs_with_creds, stbs_without_creds
        
        stbs = self.base_data.get('stbs', {})
        
        for alias, stb_data in stbs.items():
            username = stb_data.get('lname')
            password = stb_data.get('passwd')
            
            if username and password:
                stbs_with_creds.append({
                    'alias': alias,
                    'username': username,
                    'ip': stb_data.get('ip', 'N/A'),
                    'protocol': stb_data.get('protocol', 'N/A'),
                    'role': stb_data.get('role', 'N/A')
                })
            else:
                stbs_without_creds.append(alias)
        
        return stbs_with_creds, stbs_without_creds
    
    def verify(self) -> None:
        """Verification mode: show what would be migrated."""
        logger.info("="*60)
        logger.info("VERIFICATION MODE - No changes will be made")
        logger.info("="*60)
        
        if not self.load_base_file():
            return
        
        stbs_with_creds, stbs_without_creds = self.scan_credentials()
        
        print("\n" + "="*60)
        print("CREDENTIALS FOUND IN BASE.TXT")
        print("="*60)
        
        if stbs_with_creds:
            print(f"\nFound {len(stbs_with_creds)} STB(s) with credentials:\n")
            for stb in stbs_with_creds:
                print(f"  • {stb['alias']:20s} (User: {stb['username']:10s} | "\n                      f"Role: {stb['role']:10s} | IP: {stb['ip']})")
        else:
            print("\n  No credentials found.")
        
        if stbs_without_creds:
            print(f"\n\nSTBs without credentials: {len(stbs_without_creds)}")
            for alias in stbs_without_creds:
                print(f"  • {alias} (RF-only or not paired)")
        
        print("\n" + "="*60)
        print("MIGRATION PLAN")
        print("="*60)
        print(f"\nThese {len(stbs_with_creds)} credential(s) will be migrated to OS keyring:")
        print(f"  Service: {CredentialManager.SERVICE_NAME}")
        print("  Storage: Windows Credential Manager / macOS Keychain / Linux Secret Service")
        print("\nAfter migration:")
        print("  ✓ Credentials stored securely in OS keyring")
        print("  ✓ Application will try keyring first, then fall back to base.txt")
        print("  ✓ Use --remove-plaintext to remove credentials from base.txt after migration")
        
        print("\n" + "="*60)
        print("NEXT STEPS")
        print("="*60)
        print("\nTo migrate credentials:")
        print(f"  python {Path(__file__).name}")
        print("\nTo migrate AND remove plaintext (recommended after verifying):")
        print(f"  python {Path(__file__).name} --remove-plaintext")
        print("\n")
    
    def migrate(self, remove_plaintext: bool = False) -> bool:
        """
        Migrate credentials to keyring.
        
        Args:
            remove_plaintext: If True, remove credentials from base.txt after migration
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("="*60)
        logger.info("STARTING CREDENTIAL MIGRATION")
        logger.info("="*60)
        
        if not self.load_base_file():
            return False
        
        # Create backup
        if not self.backup_base_file():
            logger.error("Aborting: failed to create backup")
            return False
        
        stbs_with_creds, stbs_without_creds = self.scan_credentials()
        
        if not stbs_with_creds:
            logger.info("No credentials found to migrate")
            return True
        
        logger.info(f"Found {len(stbs_with_creds)} STB(s) with credentials")
        
        # Perform migration
        results = CredentialManager.migrate_from_base(
            self.base_data,
            remove_from_base=remove_plaintext
        )
        
        # Report results
        print("\n" + "="*60)
        print("MIGRATION RESULTS")
        print("="*60)
        
        if results['migrated']:
            print(f"\n✓ Successfully migrated ({len(results['migrated'])}):")
            for alias in results['migrated']:
                print(f"  • {alias}")
        
        if results['skipped']:
            print(f"\n⊘ Skipped ({len(results['skipped'])}):")
            for alias in results['skipped']:
                print(f"  • {alias} (no credentials found)")
        
        if results['failed']:
            print(f"\n✗ Failed ({len(results['failed'])}):")
            for alias in results['failed']:
                print(f"  • {alias}")
        
        # Save updated base.txt if we removed plaintext
        if remove_plaintext and results['migrated']:
            try:
                with open(self.base_file, 'w', encoding='utf-8') as f:
                    json.dump(self.base_data, f, indent=4)
                logger.info(f"Updated base.txt (removed plaintext credentials)")
                print("\n✓ Plaintext credentials removed from base.txt")
            except Exception as e:
                logger.error(f"Failed to update base.txt: {e}")
                logger.info(f"Restore from backup: {self.backup_file}")
                return False
        
        print("\n" + "="*60)
        print("MIGRATION COMPLETE")
        print("="*60)
        print(f"\nBackup saved: {self.backup_file}")
        
        if not remove_plaintext:
            print("\nNote: Plaintext credentials still in base.txt (backward compatibility)")
            print("To remove them, run with --remove-plaintext flag")
        
        print("\nCredentials are now stored in OS keyring:")
        print(f"  Service: {CredentialManager.SERVICE_NAME}")
        print("  Location: Windows Credential Manager / macOS Keychain / Linux Secret Service")
        
        print("\nYour application will now:")
        print("  1. Try to load credentials from keyring (secure)")
        print("  2. Fall back to base.txt if not in keyring (backward compatibility)")
        
        print("\n" + "="*60)
        
        return True


def main():
    parser = argparse.ArgumentParser(
        description='Migrate JAMboreeLite credentials from plaintext to OS keyring',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify what will be migrated (no changes)
  python migrate_credentials.py --verify
  
  # Migrate credentials (keep plaintext as fallback)
  python migrate_credentials.py
  
  # Migrate and remove plaintext from base.txt
  python migrate_credentials.py --remove-plaintext
        """
    )
    
    parser.add_argument(
        '--base-file',
        type=Path,
        default=Path('base.txt'),
        help='Path to base.txt file (default: ./base.txt)'
    )
    
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verification mode: show what will be migrated without making changes'
    )
    
    parser.add_argument(
        '--remove-plaintext',
        action='store_true',
        help='Remove plaintext credentials from base.txt after migration'
    )
    
    args = parser.parse_args()
    
    # Check if keyring is available
    try:
        import keyring
        logger.info(f"Keyring module available: {keyring.__version__}")
    except ImportError:
        logger.error("Keyring module not installed!")
        logger.error("Install with: pip install keyring==24.2.0")
        logger.error("Or run: install_keyring.bat (Windows)")
        sys.exit(1)
    
    migrator = CredentialMigrator(args.base_file)
    
    if args.verify:
        migrator.verify()
    else:
        success = migrator.migrate(remove_plaintext=args.remove_plaintext)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
