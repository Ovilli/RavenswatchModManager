// FUN_14004c900 @ 0x14004c900
// purpose-guess: EntitySettings_init2
// callers (0):


/* WARNING: Globals starting with '_' overlap smaller symbols at the same address */

void FUN_14004c900(void)

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
  FUN_1401145b0(&DAT_141413288,&local_28);
  FUN_1401145b0(&DAT_141413298,&local_18);
  uVar1 = 0;
  _DAT_1414132a8 = 0;
  if ((*local_28 == '\0') && (*local_18 == '\0')) {
    DAT_1414132b0 = 1;
  }
  else {
    DAT_1414132b0 = 0;
  }
  FUN_14048f6c0(&DAT_1414132b8);
  _DAT_1414132c8 = (undefined4)uVar1;
  _DAT_141413280 = oCGlobalEntitySettingsRef::vftable;
  _DAT_1414132d0 = uVar1;
  DAT_1414132d8 = uVar1;
  atexit(FUN_140e74840);
  return;
}

