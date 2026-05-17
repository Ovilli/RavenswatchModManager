// FUN_14000f160 @ 0x14000f160
// purpose-guess: EntitySettings_init1
// callers (0):


/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_14000f160(void)

{
  undefined8 uVar1;
  char *local_28;
  undefined4 local_20;
  char *local_18;
  undefined4 local_10;
  
  local_18 = "Common_Settings\\Barks_Manager.entity.ot";
  local_10 = 0x80000027;
  local_28 = "EntitySettings";
  local_20 = 0x8000000e;
  FUN_1401145b0(&DAT_14140f818,&local_28);
  FUN_1401145b0(&DAT_14140f828,&local_18);
  uVar1 = 0;
  _DAT_14140f838 = 0;
  if ((*local_28 == '\0') && (*local_18 == '\0')) {
    DAT_14140f840 = 1;
  }
  else {
    DAT_14140f840 = 0;
  }
  FUN_14048f6c0(&DAT_14140f848);
  _DAT_14140f858 = (undefined4)uVar1;
  _DAT_14140f810 = oCGlobalEntitySettingsRef::vftable;
  _DAT_14140f860 = uVar1;
  DAT_14140f868 = uVar1;
  atexit(FUN_140e68670);
  return;
}

