// FUN_1404f3c70 @ 0x1404f3c70
// purpose-guess: class_set_factory
// callers (939):
//   FUN_1400c15b0 @ 1400c15b0
//   FUN_140176ef0 @ 140176ef0
//   FUN_140177100 @ 140177100
//   FUN_140177440 @ 140177440
//   FUN_1401772b0 @ 1401772b0
//   FUN_140178040 @ 140178040
//   FUN_140178230 @ 140178230
//   FUN_140178930 @ 140178930
//   FUN_140178740 @ 140178740
//   FUN_140178b20 @ 140178b20
//   FUN_140178ce0 @ 140178ce0
//   FUN_1401795b0 @ 1401795b0
//   FUN_1401797a0 @ 1401797a0
//   FUN_140179ed0 @ 140179ed0
//   FUN_14017a250 @ 14017a250
//   FUN_14017a610 @ 14017a610
//   FUN_140179d10 @ 140179d10
//   FUN_14017a800 @ 14017a800
//   FUN_14017a9f0 @ 14017a9f0
//   FUN_14017abe0 @ 14017abe0
//   FUN_14017add0 @ 14017add0
//   FUN_14017afc0 @ 14017afc0
//   FUN_14017b1b0 @ 14017b1b0
//   FUN_14017b3a0 @ 14017b3a0
//   FUN_14017b590 @ 14017b590
//   FUN_14017b780 @ 14017b780
//   FUN_14017b970 @ 14017b970
//   FUN_14017bb60 @ 14017bb60
//   FUN_14017bd50 @ 14017bd50
//   FUN_14017bf40 @ 14017bf40
//   FUN_14017c130 @ 14017c130
//   FUN_14017cc10 @ 14017cc10
//   FUN_14017ce00 @ 14017ce00
//   FUN_14017cff0 @ 14017cff0
//   FUN_14017d1e0 @ 14017d1e0
//   FUN_14017d3d0 @ 14017d3d0
//   FUN_14017d560 @ 14017d560
//   FUN_14017d730 @ 14017d730
//   FUN_14017d900 @ 14017d900
//   FUN_14017dad0 @ 14017dad0
//   FUN_14017dca0 @ 14017dca0
//   FUN_14017de70 @ 14017de70
//   FUN_14017e040 @ 14017e040
//   FUN_14017e210 @ 14017e210
//   FUN_14017e3b0 @ 14017e3b0
//   FUN_14017e570 @ 14017e570
//   FUN_14017e760 @ 14017e760
//   FUN_14017e950 @ 14017e950
//   FUN_14017eae0 @ 14017eae0
//   FUN_14017ecb0 @ 14017ecb0


void FUN_1404f3c70(undefined8 param_1,undefined8 param_2,code *param_3)

{
  uint uVar1;
  uint uVar2;
  uint uVar3;
  longlong *plVar4;
  undefined8 *puVar5;
  uint uVar6;
  code *pcVar7;
  
  puVar5 = (undefined8 *)FUN_140215b10(DAT_14140ded0,*(undefined4 *)(DAT_14140ded0 + 8));
  *puVar5 = param_2;
  plVar4 = DAT_14140dee0;
  pcVar7 = (code *)0x0;
  if (param_3 != _guard_check_icall) {
    pcVar7 = param_3;
  }
  uVar1 = *(uint *)(DAT_14140dee0 + 1);
  uVar2 = *(uint *)((longlong)DAT_14140dee0 + 0xc);
  uVar6 = uVar1 + 1;
  if (uVar2 < uVar6) {
    uVar3 = 8;
    if (8 < uVar2) {
      uVar3 = uVar2;
    }
    for (; uVar3 < uVar6; uVar3 = uVar3 * 2) {
    }
    FUN_140153520(DAT_14140dee0);
  }
  *(uint *)(plVar4 + 1) = uVar6;
  *(code **)(*plVar4 + (ulonglong)uVar1 * 8) = pcVar7;
  return;
}

